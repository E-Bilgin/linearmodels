import numpy as np
from numpy.linalg import pinv

from linearmodels.asset_pricing.results import LinearFactorModelResults, GMMFactorModelResults
from linearmodels.iv.covariance import KERNEL_LOOKUP, _cov_kernel
from linearmodels.iv.data import IVData
from linearmodels.utility import AttrDict, WaldTestStatistic
from scipy.optimize import minimize


def callback_factory(obj, args, disp=1):
    d = {'iter': 0}
    disp = int(disp)

    def callback(params):
        fval = obj(params, *args)
        if disp > 0 and (d['iter'] % disp == 0):
            print('Iteration: {0}, Objective: {1}'.format(d['iter'], fval))
        d['iter'] += 1

    return callback


class TradedFactorModel(object):
    r"""Linear factor models estimator applicable to traded factors
    
    Parameters
    ----------
    portfolios : array-like
        Test portfolio returns (nobs by nportfolio)
    factors : array-like
        Priced factor returns (nobs by nfactor 
   
    Notes
    -----
    Implements both time-series estimators of risk premia, factor loadings 
    and zero-alpha tests.
    
    The model estimated is 
    
    .. math::
    
        r_{it}^e = \alpha_i + f_t \beta_i + \epsilon_{it}
    
    where :math:`r_{it}^e` is the excess return on test portfolio i and 
    :math:`f_t` are the traded factor returns.  The model is directly 
    tested using the estimated values :math:`\hat{\alpha}_i`. Risk premia, 
    :math:`\lambda_i` are estimated using the sample averages of the factors,
    which must be excess returns on traded portfolios.
    """

    def __init__(self, portfolios, factors):
        self.portfolios = IVData(portfolios, var_name='portfolio')
        self.factors = IVData(factors, var_name='factor')
        self._name = self.__class__.__name__

    def fit(self, cov_type='robust', debiased=True, **cov_config):
        """
        Estimate model parameters
        
        Parameters
        ----------
        cov_type : str, optional
            Name of covariance estimator
        debiased : bool, optional
            Flag indicating whether to debias the covariance estimator using 
            a degree of freedom adjustment
        **cov_config : dict
            Additional covariance-specific options.  See Notes.
        
        Returns
        -------
        results : LinearFactorModelResults
            Results class with parameter estimates, covariance and test statistics
        
        Notes
        -----
        Supported covariance estiamtors are:
        
        * 'robust' - Heteroskedasticity-robust covariance estimator
        * 'kernel' - Heteroskedasticity and Autocorrelation consistent (HAC) 
          covariance estimator
          
        The kernel covariance estimator takes the optional arguments 
        ``kernel``, one of 'bartlett', 'parzen' or 'qs' (quadratic spectral) 
        and ``bandwidth`` (a positive integer).
        """
        # TODO: Homoskedastic covariance

        p = self.portfolios.ndarray
        f = self.factors.ndarray
        nportfolio = p.shape[1]
        nobs, nfactor = f.shape
        fc = np.c_[np.ones((nobs, 1)), f]
        rp = f.mean(0)[:, None]
        fe = f - f.mean(0)
        b = pinv(fc) @ p
        eps = p - fc @ b
        alphas = b[:1].T

        nloading = (nfactor + 1) * nportfolio
        xpxi = np.eye(nloading + nfactor)
        xpxi[:nloading, :nloading] = np.kron(np.eye(nportfolio), pinv(fc.T @ fc / nobs))
        f_rep = np.tile(fc, (1, nportfolio))
        eps_rep = np.tile(eps, (nfactor + 1, 1))  # 1 2 3 ... 25 1 2 3 ...
        eps_rep = eps_rep.ravel(order='F')
        eps_rep = np.reshape(eps_rep, (nobs, (nfactor + 1) * nportfolio), order='F')
        xe = f_rep * eps_rep
        xe = np.c_[xe, fe]
        if cov_type in ('robust', 'heteroskedastic'):
            xeex = xe.T @ xe / nobs
            rp_cov = fe.T @ fe / nobs
        elif cov_type == 'kernel':
            kernel = cov_config.get('kernel', 'bartlett')
            bw = cov_config.get('bandwidth', None)
            bw = int(np.ceil(4 * (nobs / 100) ** (2 / 9))) if bw is None else bw
            w = KERNEL_LOOKUP[kernel](bw, nobs - 1)
            xeex = _cov_kernel(xe, w)
            rp_cov = _cov_kernel(fe, w)
        else:
            raise ValueError('Unknown cov_type: {0}'.format(cov_type))
        debiased = int(bool(debiased))
        df = fc.shape[1]
        full_vcv = xpxi @ xeex @ xpxi / (nobs - debiased * df)
        vcv = full_vcv[:nloading, :nloading]
        rp_cov = rp_cov / (nobs - debiased)

        # Rearrange VCV
        order = np.reshape(np.arange((nfactor + 1) * nportfolio), (nportfolio, nfactor + 1))
        order = order.T.ravel()
        vcv = vcv[order][:, order]

        # Return values
        alpha_vcv = vcv[:nportfolio, :nportfolio]
        stat = float(alphas.T @ pinv(alpha_vcv) @ alphas)
        jstat = WaldTestStatistic(stat, 'All alphas are 0', nportfolio, name='J-statistic')
        params = b.T
        betas = b[1:].T
        residual_ss = (eps ** 2).sum()
        e = p - p.mean(0)[None, :]
        total_ss = (e ** 2).sum()
        r2 = 1 - residual_ss / total_ss
        param_names = []
        for portfolio in self.portfolios.cols:
            param_names.append('alpha-{0}'.format(portfolio))
            for factor in self.factors.cols:
                param_names.append('beta-{0}-{1}'.format(portfolio, factor))
        for factor in self.factors.cols:
            param_names.append('lambda-{0}'.format(factor))

        res = AttrDict(params=params, cov=full_vcv, betas=betas, rp=rp, rp_cov=rp_cov,
                       alphas=alphas, alpha_vcv=alpha_vcv, jstat=jstat,
                       rsquared=r2, total_ss=total_ss, residual_ss=residual_ss,
                       param_names=param_names, portfolio_names=self.portfolios.cols,
                       factor_names=self.factors.cols, name=self._name,
                       cov_type=cov_type, model=self, nobs=nobs, rp_names=self.factors.cols)

        return LinearFactorModelResults(res)


class LinearFactorModel(TradedFactorModel):
    r"""Linear factor model estimator 

    Parameters
    ----------
    portfolios : array-like
        Test portfolio returns (nobs by nportfolio)
    factors : array-like
        Priced factorreturns (nobs by nfactor 
    sigma : array-like, optional
        Positive definite residual covariance (nportfolio by nportfolio) 

    Notes
    -----
    GLS estimation using ``sigma`` has not been implemented
    
    Suitable for traded or non-traded factors.
    
    Implements a 2-step estimator of risk premia, factor loadings and model 
    tests.
    
    The first stage model estimated is 
    
    .. math::
    
        r_{it}^e = a_i + f_t \beta_i + \epsilon_{it}
    
    where :math:`r_{it}^e` is the excess return on test portfolio i and 
    :math:`f_t` are the traded factor returns.  The parameters :math:`a_i`
    are required to allow non-traded to be tested, but are not economically
    interesting.  These are not reported.
      
    The second stage model uses the estimated factor loadings from the first 
    and is 
    
    .. math::
    
        \bar{r}_i^e = \hat{\beta}_i^\prime \lambda + \eta_i
    
    where :math:`\bar{r}_i^e` is the average excess return to portfolio i.    
    
    The model is tested using the estimated values 
    :math:`\hat{\alpha}_i=\hat{\eta}_i`.     
    """

    def __init__(self, portfolios, factors, *, sigma=None):
        super(LinearFactorModel, self).__init__(portfolios, factors)
        self._sigma = sigma

    def fit(self, excess_returns=True, cov_type='robust', **cov_config):
        """
        Estimate model parameters
        
        Parameters
        ----------
        excess_returns : bool, optional
            Flag indicating whether returns are excess or not.  If False, the 
            risk-free rate is jointly estimated with the other risk premia.
        cov_type : str, optional
            Name of covariance estimator
        **cov_config
            Additional covariance-specific options.  See Notes.

        Returns
        -------
        results : LinearFactorModelResults
            Results class with parameter estimates, covariance and test statistics

        Notes
        -----
        The kernel covariance estimator takes the optional arguments 
        ``kernel``, one of 'bartlett', 'parzen' or 'qs' (quadratic spectral) 
        and ``bandwidth`` (a positive integer).
        """
        # TODO: Kernel estimator
        # TODO: Refactor commonalities in estimation
        excess_returns = bool(excess_returns)
        nrf = int(not excess_returns)
        f = self.factors.ndarray
        nobs, nfactor = f.shape
        p = self.portfolios.ndarray
        nportfolio = p.shape[1]

        # Step 1, n regressions to get B
        fc = np.c_[np.ones((nobs, 1)), f]
        b = np.linalg.lstsq(fc, p)[0]  # nf+1 by np
        eps = p - fc @ b
        if excess_returns:
            betas = b[1:].T
        else:
            betas = b.T.copy()
            betas[:, 0] = 1.0

        # Step 2, t regressions to get lambda(T)
        # if self._sigma is not None:
        #    vals, vecs = np.linalg.eigh(self._sigma)
        #    sigma_m12 = vecs @ np.diag(1.0 / np.sqrt(vals)) @ vecs.T
        # else:
        #    sigma_m12 = np.eye(nportfolio)

        lam = np.linalg.lstsq(betas, p.mean(0)[:, None])[0]

        # Moments
        f_rep = np.tile(fc, (1, nportfolio))
        eps_rep = np.tile(eps, (nfactor + 1, 1))
        eps_rep = np.reshape(eps_rep.T, (nportfolio * (nfactor + 1), nobs)).T
        expected = betas @ lam
        pricing_errors = p - expected.T
        alphas = pricing_errors.mean(0)[:, None]

        moments = np.c_[f_rep * eps_rep, pricing_errors @ betas, pricing_errors - alphas.T]
        S = moments.T @ moments / nobs
        # Jacobian
        G = np.eye(S.shape[0])
        s1, s2 = 0, (nfactor + 1) * nportfolio,
        s3 = s2 + (nfactor + nrf)
        fpf = fc.T @ fc / nobs
        G[:s2, :s2] = np.kron(np.eye(nportfolio), fpf)
        G[s2:s3, s2:s3] = betas.T @ betas
        for i in range(nportfolio):
            _lam = lam if excess_returns else lam[1:]
            block = betas[[i]].T @ _lam.T
            if excess_returns:
                block -= alphas[i] * np.eye(nfactor)
            else:
                block -= np.r_[np.zeros((1, nfactor)), alphas[i] * np.eye(nfactor)]

            block = np.c_[np.zeros((nfactor + nrf, 1)), block]
            G[s2:s3, (i * (nfactor + 1)):((i + 1) * (nfactor + 1))] = block
        zero_lam = np.r_[[[0]], lam] if excess_returns else np.r_[[[0]], lam[1:]]
        G[s3:, :s2] = np.kron(np.eye(nportfolio), zero_lam.T)
        Ginv = np.linalg.inv(G)
        # VCV
        full_vcv = Ginv @ S @ Ginv.T / nobs
        alpha_vcv = full_vcv[s3:, s3:]
        stat = float(alphas.T @ np.linalg.inv(alpha_vcv) @ alphas)
        jstat = WaldTestStatistic(stat, 'All alphas are 0', nportfolio - nfactor,
                                  name='J-statistic')

        total_ss = ((p - p.mean(0)[None, :]) ** 2).sum()
        residual_ss = (eps ** 2).sum()
        r2 = 1 - residual_ss / total_ss
        rp = lam
        rp_cov = full_vcv[s2:s3, s2:s3]
        betas = betas if excess_returns else betas[:, 1:]
        params = np.c_[alphas, betas]
        param_names = []
        for portfolio in self.portfolios.cols:
            param_names.append('alpha-{0}'.format(portfolio))
            for factor in self.factors.cols:
                param_names.append('beta-{0}-{1}'.format(portfolio, factor))
        if not excess_returns:
            param_names.append('lambda-risk_free')
        for factor in self.factors.cols:
            param_names.append('lambda-{0}'.format(factor))
        # Pivot vcv to remove unnecessary and have correct order
        order = np.reshape(np.arange(s2), (nportfolio, nfactor + 1))
        order[:, 0] = np.arange(s3, s3 + nportfolio)
        order = order.ravel()
        order = np.r_[order, s2:s3]
        full_vcv = full_vcv[order][:, order]
        factor_names = list(self.factors.cols)
        rp_names = factor_names[:]
        if not excess_returns:
            rp_names.insert(0, 'risk_free')
        res = AttrDict(params=params, cov=full_vcv, betas=betas, rp=rp, rp_cov=rp_cov,
                       alphas=alphas, alpha_vcv=alpha_vcv, jstat=jstat,
                       rsquared=r2, total_ss=total_ss, residual_ss=residual_ss,
                       param_names=param_names, portfolio_names=self.portfolios.cols,
                       factor_names=factor_names, name=self._name,
                       cov_type=cov_type, model=self, nobs=nobs, rp_names=rp_names)

        return LinearFactorModelResults(res)


class LinearFactorModelGMM(TradedFactorModel):
    r"""GMM estimator of Linear factor models 

    Parameters
    ----------
    portfolios : array-like
        Test portfolio returns (nobs by nportfolio)
    factors : array-like
        Priced factorreturns (nobs by nfactor 

    Notes
    -----
    Suitable for traded or non-traded factors.

    Implements a GMM estimator of risk premia, factor loadings and model 
    tests.

    The moments are  

    .. math::

        \left[\begin{array}{c}
        \epsilon_{t}\otimes\left[1\:f_{t}^{\prime}\right]^{\prime}\\
        f_{t}-\mu
        \end{array}\right]
    
    and
    
    .. math::
    
      \epsilon_{t}=r_{t}-\left[1_{N}\;\beta\right]\lambda-\beta\left(f_{t}-\mu\right)

    where :math:`r_{it}^e` is the excess return on test portfolio i and 
    :math:`f_t` are the traded factor returns.  
    
    The model is tested using the optimized objective function using the 
    usual GMM J statistic.
    """

    def __init__(self, factors, portfolios):
        super(LinearFactorModelGMM, self).__init__(factors, portfolios)

    def fit(self, excess_returns=True, steps=2, disp=10, max_iter=1000,
            cov_type='robust', debiased=True, **cov_config):
        """
        Estimate model parameters

        Parameters
        ----------
        excess_returns : bool, optional
            Flag indicating whether returns are excess or not.  If False, the 
            risk-free rate is jointly estimated with the other risk premia.
        steps : int, optional
            Number of steps to use when estimating parameters.  2 corresponds 
            to the standard efficient gmm estimator. Higher values will
            iterate until convergence or up to the number of steps given
        disp : int, optional
            Number of iterations between printed update. 0 or negative values 
            suppress iterative output
        max_iter : int, positive, optional
            Maximum number of iterations when minimizing objective
        cov_type : str, optional
            Name of covariance estimator
        **cov_config
            Additional covariance-specific options.  See Notes.

        Returns
        -------
        results : GMMFactorModelResults
            Results class with parameter estimates, covariance and test statistics

        Notes
        -----
        The kernel covariance estimator takes the optional arguments 
        ``kernel``, one of 'bartlett', 'parzen' or 'qs' (quadratic spectral) 
        and ``bandwidth`` (a positive integer).
        """

        nobs, n = self.portfolios.shape
        k = self.factors.shape[1]
        nrf = int(not bool(excess_returns))
        # 1. Starting Values - use 2 pass
        mod = LinearFactorModel(self.portfolios, self.factors)
        res = mod.fit(excess_returns=excess_returns)
        betas = res.betas.values.ravel()
        lam = res.risk_premia.values
        mu = self.factors.ndarray.mean(0)
        sv = np.r_[betas, lam, mu][:, None]
        g = self._moments(sv, excess_returns)
        # TODO: allow different weights type
        w = np.linalg.inv(g.T @ g / nobs)
        args = (excess_returns, w)

        # 2. Step 1 using w = inv(s) from SV
        callback = callback_factory(self._j, args, disp=disp)
        res = minimize(self._j, sv, args=args, callback=callback,
                       options={'disp': bool(disp), 'maxiter': max_iter})
        params = res.x
        last_obj = res.fun
        # 3. Step 2 using step 1 estimates
        # TODO: Add convergence criteria
        for i in range(steps - 1):
            g = self._moments(params, excess_returns)
            w = np.linalg.inv(g.T @ g / nobs)
            args = (excess_returns, w)

            # 2. Step 1 using w = inv(s) from SV
            callback = callback_factory(self._j, args, disp=disp)
            res = minimize(self._j, params, args=args, callback=callback,
                           options={'disp': bool(disp), 'maxiter': max_iter})
            params = res.x
            obj = res.fun
            if np.abs(obj - last_obj) < 1e-6:
                break
            last_obj = obj

        # 4. Compute final S and G for inference
        g = self._moments(params, excess_returns)
        s = g.T @ g / nobs
        jac = self._jacobian(params, excess_returns)

        full_vcv = np.linalg.inv(jac.T @ np.linalg.inv(s) @ jac) / nobs
        rp = params[(n * k):(n * k + k + nrf)]
        rp_cov = full_vcv[(n * k):(n * k + k + nrf), (n * k):(n * k + k + nrf)]
        alphas = g.mean(0)[0:(n * (k+1)):(k + 1), None]
        alpha_vcv = s[0:(n * (k+1)):(k + 1), 0:(n * (k+1)):(k + 1)] / nobs  # TODO: Fix this
        stat = self._j(params, excess_returns, w)
        jstat = WaldTestStatistic(stat, 'All alphas are 0', n, name='J-statistic')

        # R2 calculation
        betas = np.reshape(params[:(n * k)], (n, k))
        resids = self.portfolios.ndarray - self.factors.ndarray @ betas.T
        resids -= resids.mean(0)[None, :]
        residual_ss = (resids ** 2).sum()
        total = self.portfolios.ndarray
        total = total - total.mean(0)[None, :]
        total_ss = (total ** 2).sum()
        r2 = 1.0 - residual_ss / total_ss
        param_names = []
        for portfolio in self.portfolios.cols:
            for factor in self.factors.cols:
                param_names.append('beta-{0}-{1}'.format(portfolio, factor))
        if not excess_returns:
            param_names.append('lambda-risk_free')
        param_names.extend(['lambda-{0}'.format(f) for f in self.factors.cols])
        param_names.extend(['mu-{0}'.format(f) for f in self.factors.cols])
        rp_names = param_names[(n * k):(n * k + k + nrf)]
        params = np.c_[alphas, betas]
        # 5. Return values
        res = AttrDict(params=params, cov=full_vcv, betas=betas, rp=rp, rp_cov=rp_cov,
                       alphas=alphas, alpha_vcv=alpha_vcv, jstat=jstat,
                       rsquared=r2, total_ss=total_ss, residual_ss=residual_ss,
                       param_names=param_names, portfolio_names=self.portfolios.cols,
                       factor_names=self.factors.cols, name=self._name,
                       cov_type=cov_type, model=self, nobs=nobs, rp_names=rp_names)

        return GMMFactorModelResults(res)

    def _moments(self, parameters, excess_returns):
        """Calculate nobs by nmoments moment condifions"""
        nrf = int(not excess_returns)
        p = self.portfolios.ndarray
        nobs, n = p.shape
        f = self.factors.ndarray
        k = f.shape[1]
        s1, s2 = n * k, n * k + k + nrf
        betas = parameters[:s1]
        lam = parameters[s1:s2]
        mu = parameters[s2:]
        betas = np.reshape(betas, (n, k))
        expected = np.c_[np.ones((n, nrf)), betas] @ lam
        fe = f - mu.T
        eps = p - expected.T - fe @ betas.T
        f = np.c_[np.ones((nobs, 1)), f]
        f = np.tile(f, (1, n))
        eps = np.reshape(np.tile(eps, (k + 1, 1)).T, (n * (k + 1), nobs)).T
        g = np.c_[eps * f, fe]
        return g

    def _j(self, parameters, excess_returns, w):
        """Objective function"""
        g = self._moments(parameters, excess_returns)
        nobs = self.portfolios.shape[0]
        gbar = g.mean(0)[:, None]
        return nobs * float(gbar.T @ w @ gbar)

    def _jacobian(self, params, excess_returns):
        """Jacobian matrix for inference"""
        nobs, k = self.factors.shape
        n = self.portfolios.shape[1]
        nrf = int(bool(not excess_returns))
        jac = np.zeros((n * k + n + k, params.shape[0]))
        s1, s2 = (n * k), (n * k) + k + nrf
        betas = params[:s1]
        betas = np.reshape(betas, (n, k))
        lam = params[s1:s2]
        mu = params[-k:]
        lam_tilde = lam if excess_returns else lam[1:]
        f = self.factors.ndarray
        fe = f - mu.T + lam_tilde.T
        f_aug = np.c_[np.ones((nobs, 1)), f]
        fef = f_aug.T @ fe / nobs
        r1 = n * (k + 1)
        jac[:r1, :s1] = np.kron(np.eye(n), fef)

        jac12 = np.zeros((r1, (k + nrf)))
        jac13 = np.zeros((r1, k))
        iota = np.ones((nobs, 1))
        for i in range(n):
            if excess_returns:
                b = betas[[i]]
            else:
                b = np.c_[[1], betas[[i]]]
            jac12[(i * (k + 1)):(i + 1) * (k + 1)] = f_aug.T @ (iota @ b) / nobs

            b = betas[[i]]
            jac13[(i * (k + 1)):(i + 1) * (k + 1)] = -f_aug.T @ (iota @ b) / nobs
        jac[:r1, s1:s2] = jac12
        jac[:r1, s2:] = jac13
        jac[-k:, -k:] = np.eye(k)

        return jac