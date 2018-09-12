#!groovy

// Jenkins configuration
// 1. Install and enable plugin "Pipeline: Multibranch"
// 2. Install and enable plugin "Basic Branch Build Strategies"
// 3. Install and enable plugin "Git Parameter"
// 4. Add credentials in Jenkins
//    a. Add github credentials. id="github-loom", kind="SSH Username with private key", passphrase=[blank], username="jenkins". Add the same private key to the github repo.
//    b. Add dockerhub credentials with access to loomengine dockerhub repo. kind="Username with password", id="dockerhub-loom".
//    c. Add "loom" credentials, to be applied to loom server started during tests. kind="Username with password", id="loom-admin"
//    d. (Optional) Add github username-password credentials to be used with "Github" plugin. Only supports username-password. Not needed to access a public repo, but the quota for scanning github with no credentials may be too low.
// 5. Create a MultiBranch Pipeline named "loom"
//    a. Add "Branch sources" > "Github"
//       i. (options) select any valid username/password for github. This is not needed for public repo, but will increase the quota.
//       ii. Select owner and repo ("StanfordBioinformatics", "loom")
//       iii. Discover branches: strategy = "All branches"
//       iv. Discover pull requests from origin: strategy = "Merging the pull request with the target branch revision"
//       v. Trust: "from users with admin or write permission"
//       vi. Discover tags
//       vii. Advanced clone behaviors: Fetch tags = True, shallow clone depth = 0.
//       viii. Clean before checkout.
//       ix. Build strategies: Change requests, Regular branches, Tags (ignore tags older than 7 days)
// 6. In gihub, configure Jenkins web-hooks (e.g. https://jenkins.loomengine.org/github-webhook/)
// 7. Add deployment settings in ~jenkins/.loom-deploy-settings
//    a. Settings in ~jenkins/.loom-deploy-settings/loom.conf
//    b. Resources in ~jenkins/.loom-deploy-settings/resources/
// 8. Add pypi credentials in ~jenkins/.pypirc
// 9. Install Docker on the Jenkins host

pipeline {
  agent any
  environment {
    // If this is a tagged build, version will be TAG_NAME.
    // Otherwise take version from git commit
    VERSION="${ TAG_NAME ? TAG_NAME : GIT_COMMIT }"
    LOOM_SETTINGS_HOME="${WORKSPACE}/.loom/"
    LOOM_SERVER_NAME="${BUILD_TAG.replaceAll(/_/,'-').replaceAll(/\./,'-').toLowerCase()}"
    GOOGLE_APPLICATION_CREDENTIALS="${HOME}/.loom-deploy-settings/resources/gcp-service-account-key.json"
  }
  stages {
    stage('Build Docker Image') {
      steps {
        sh 'env' // for debugging
        sh 'docker build --build-arg LOOM_VERSION=${VERSION} . -t loomengine/loom:${VERSION}'
        script {
	  if (!env.TAG_NAME) {
            sh 'docker build --build-arg LOOM_VERSION=${VERSION} . -t loomengine/loom:${GIT_BRANCH}'
          }
        }
      }
    }
    stage('Unit Tests') {
      steps {
        sh 'docker run loomengine/loom:${VERSION} /loom/src/bin/run-unit-tests.sh'
      }
    }
    stage('Push Docker Image') {
      steps {
        // "docker push" requires that jenkins user first be authenticated
	// with "docker login" on host OS.
	// Hashed docker credentials are written to ~/.docker/config.json
	// and remain valid as long as username and password are valid
        sh 'docker push loomengine/loom:${VERSION}'
	script {
          if (!env.TAG_NAME) {
            sh 'docker push loomengine/loom:${GIT_BRANCH}'
          }
        }
      }
    }
    stage('Deploy Test Environment') {
      steps {
        // Create doc building environment
	sh 'virtualenv doc-env'
	sh '. doc-env/bin/activate && pip install -r doc/requirements.pip'
        // Install loom client locally
        sh 'virtualenv env'
        sh 'build-tools/set-version.sh ${VERSION}'
        sh '. env/bin/activate && pip install -r build-tools/requirements-dev.pip'
        sh '. env/bin/activate && build-tools/build-loom-packages.sh'
	sh '. env/bin/activate && build-tools/install-loom-packages.sh'
        sh 'if [ ! -f ~/.loom-deploy-settings/loom.conf ]; then echo ERROR Loom deployment settings not found; fi'
	sh 'mkdir $WORKSPACE/.loom'
        withCredentials([[$class: 'UsernamePasswordMultiBinding', credentialsId:'loom-admin',
          usernameVariable: 'USERNAME', passwordVariable: 'PASSWORD']
        ]) {
	  script {
	    loomServerStarted = true
	  }
          sh '. env/bin/activate && loom server start -s ${HOME}/.loom-deploy-settings/loom.conf -r ${HOME}/.loom-deploy-settings/resources/ -e LOOM_ADMIN_USERNAME=${USERNAME} -e LOOM_ADMIN_PASSWORD=${PASSWORD}'
          sh '. env/bin/activate && loom auth login $USERNAME -p $PASSWORD'
	}
      }
    }
    stage('Doc build tests') {
      steps {
        sh '. doc-env/bin/activate && cd doc && make html'
      }
    }
    stage('Smoke Tests') {
      steps {
        sh '. env/bin/activate && loom test smoke'
      }
    }
    stage('Integration Tests') {
      when {
        expression { env.TAG_NAME }
      }
      steps {
        sh '. env/bin/activate && loom test integration'
      }
    }
    stage('Publish Release') {
      when {
        expression { env.TAG_NAME }
      }
      steps {
        sh 'echo Publish Release'
      }
    }
    stage('Release to PyPi') {
      when {
        expression { env.TAG_NAME }
      }
      steps {
        sh '. env/bin/activate && build-tools/pypi-release.sh'
      }
    }
    stage('Verify PyPi release can be installed') {
      when {
        expression { env.TAG_NAME }
      }
      options { retry(30) } // Retry for up to 600 seconds (plus runtime)
      steps {
        sh 'sleep 20'
        sh 'rm -rf env-pypi && virtualenv env-pypi'
        sh '. env-pypi/bin/activate && pip install loomengine==$VERSION loomengine_server==$VERSION loomengine_worker==$VERSION'
        sh '. env-pypi/bin/activate && python -c "import loomengine, loomengine_server, loomengine_worker, loomengine_utils"'
        sh '. env-pypi/bin/activate && loom -h'
      }
    }
  }
  post {
    always ('Cleanup') {
      script {
        if (loomServerStarted) {
          sh '. env/bin/activate && loom server delete --confirm-server-name ${LOOM_SERVER_NAME}'
	}
	// uses Workspace Cleanup Plugin to delete workspace dir.
	cleanWs()
      }
    }
    success {
      emailext (
        subject: "SUCCESSFUL: Job '${env.JOB_NAME} [${env.BUILD_NUMBER}]'",
        body: """SUCCESSFUL: Job '${env.JOB_NAME} [${env.BUILD_NUMBER}]':
          Check console output at ${env.BUILD_URL}'""",
        recipientProviders: [[$class: 'DevelopersRecipientProvider']]
      )
    }
    failure {
      emailext (
        subject: "FAILED: Job '${env.JOB_NAME} [${env.BUILD_NUMBER}]'",
        body: """FAILED: Job '${env.JOB_NAME} [${env.BUILD_NUMBER}]':
          Check console output at ${env.BUILD_URL}""",
        recipientProviders: [[$class: 'DevelopersRecipientProvider']]
      )
    }
  }
}
