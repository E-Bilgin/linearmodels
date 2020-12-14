#!/usr/bin/env bash

echo "Set git email and name"
git config user.email "kevin.k.sheppard@gmail.com"
git config user.name "Kevin Sheppard"
echo "Checkout pages"
git checkout gh-pages
echo "Remove devel"
rm -rf devel
echo "Make a new devel"
mkdir devel
echo "Checking for tag"
GIT_TAG=$(git name-rev --name-only --tags HEAD)
if [[ ${GIT_TAG} == "undefined" ]]; then
  echo "Tag is ${GIT_TAG}. Not updating main documents"
else
  echo "Tag ${GIT_TAG} is defined"
  echo "Copy docs to root"
  echo cp -R ${PWD}/doc/build/html/ ${PWD}/
  cp -R ${PWD}/doc/build/html/* ${PWD}
fi
echo "Copy docs to devel"
echo cp -R ${PWD}/doc/build/html/ ${PWD}/devel/
cp cp -R ${PWD}/doc/build/html/ ${PWD}/devel/
echo "Add devel"
git add devel/.

echo "Change remote"
git remote set-url origin https://bashtage:"${GH_PAGES_TOKEN}"@github.com/bashtage/linearmodels.git
echo "Github Actions doc build after commit ${GITHUB_REF##*/}"
git commit -a -m "Github Actions doc build after commit ${GITHUB_REF##*/}"
echo "Push"
git push -f


