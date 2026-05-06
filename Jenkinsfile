pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        DOCKER_IMAGE = 'mAmineChniti/accountia-ai'
        IMAGE_TAG = '1.0'
        DOCKERHUB_CREDENTIALS_ID = 'dockerhub-credentials'
        PYTHONUNBUFFERED = '1'
        PIP_DISABLE_PIP_VERSION_CHECK = '1'
        PIP_NO_CACHE_DIR = '1'
        SONAR_HOST_URL = 'http://localhost:9000'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Install Dependencies') {
            steps {
                sh '''
                    # Ensure Python 3.11 is available
                    which python3.11 || (echo "Python 3.11 not found" && exit 1)
                    python3.11 --version
                    
                    python3.11 -m venv venv
                    ./venv/bin/python3.11 -m pip install --upgrade pip
                    ./venv/bin/python3.11 -m pip install -r requirements.txt coverage
                '''
            }
        }

        stage('Lint') {
            steps {
                sh './venv/bin/ruff check app/'
            }
        }

        stage('Format') {
            steps {
                sh './venv/bin/ruff format --check app/'
            }
        }

        stage('Tests') {
            steps {
                sh '''
                    ./venv/bin/python3.11 -m coverage run -m pytest tests/ -v
                    ./venv/bin/python3.11 -m coverage xml -o coverage.xml
                    ./venv/bin/python3.11 -m coverage report
                '''
            }
        }

        stage('SonarQube Analysis') {
            steps {
                withCredentials([string(credentialsId: 'sonar', variable: 'SONAR_TOKEN')]) {
                    sh '''
                        set -e
                        if [ -z "${SONAR_HOST_URL:-}" ]; then
                          echo "WARN: SONAR_HOST_URL not configured. Skipping SonarQube analysis."
                          exit 0
                        fi

                        if command -v sonar-scanner >/dev/null 2>&1; then
                          SCANNER_BIN=sonar-scanner
                        else
                          echo "Installing sonar-scanner CLI..."
                          wget --timeout=30 --tries=3 \
                            https://binaries.sonarsource.com/Distribution/sonar-scanner-cli/sonar-scanner-cli-5.0.1.3006-linux.zip
                          unzip -qo sonar-scanner-cli-5.0.1.3006-linux.zip
                          chmod +x sonar-scanner-5.0.1.3006-linux/bin/sonar-scanner
                          SCANNER_BIN="$PWD/sonar-scanner-5.0.1.3006-linux/bin/sonar-scanner"
                        fi

                        "$SCANNER_BIN" \
                          -Dsonar.host.url="$SONAR_HOST_URL" \
                          -Dsonar.token="$SONAR_TOKEN" \
                          -Dsonar.qualitygate.wait=true \
                          -Dsonar.qualitygate.timeout=300
                    '''
                }
            }
        }

        stage('Build') {
            steps {
                sh './venv/bin/python3.11 -c "from app.main import app; print(\'✓ App builds successfully\')"'
            }
        }

        stage('Docker Build & Push') {
            steps {
                script {
                    sh '''
                        # Check if Docker daemon is accessible for Jenkins user
                        if ! docker ps > /dev/null 2>&1; then
                            echo "Docker daemon is not accessible for Jenkins user. Skipping Docker build & push."
                            exit 0
                        fi
                        
                                                # Create isolated Docker config without credential helpers
                                                mkdir -p .docker-ci
                                                cat > .docker-ci/config.json << 'EOF'
{
    "auths": {},
    "credHelpers": {}
}
EOF
                    '''
                    try {
                        sh '''
                            # Build without authentication (public image)
                            DOCKER_BUILDKIT=0 DOCKER_CONFIG="$PWD/.docker-ci" docker build --pull -t "$DOCKER_IMAGE:$IMAGE_TAG" -t "$DOCKER_IMAGE:latest" .
                        '''
                        
                        withCredentials([usernamePassword(credentialsId: DOCKERHUB_CREDENTIALS_ID, usernameVariable: 'DOCKERHUB_USERNAME', passwordVariable: 'DOCKERHUB_PASSWORD')]) {
                            sh '''
                                # Now login with credentials and push
                                printf '%s' "$DOCKERHUB_PASSWORD" | DOCKER_CONFIG="$PWD/.docker-ci" docker login -u "$DOCKERHUB_USERNAME" --password-stdin
                                DOCKER_CONFIG="$PWD/.docker-ci" docker push "$DOCKER_IMAGE:$IMAGE_TAG"
                                DOCKER_CONFIG="$PWD/.docker-ci" docker push "$DOCKER_IMAGE:latest"
                            '''
                        }
                    } catch (Exception e) {
                        echo "WARNING: Docker build/push failed or Docker credentials are unavailable: ${e.message}. Skipping Docker stage."
                    }
                }
            }
        }
    }

    post {
        success {
            echo 'AI CI pipeline completed successfully.'
        }

        failure {
            echo 'AI CI pipeline failed. Check the stage logs above.'
        }

        cleanup {
            archiveArtifacts artifacts: '.scannerwork/report-task.txt,coverage.xml', allowEmptyArchive: true
            sh 'rm -rf .pytest_cache .coverage coverage.xml sonar-scanner-* sonar-scanner-cli-*.zip .scannerwork/ || true'
            sh 'rm -rf .docker-ci || true'
        }
    }
}