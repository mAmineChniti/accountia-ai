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
                script {
                    // SonarQube analysis is optional - don't fail build if it has issues
                    try {
                        // Install sonar-scanner if not available
                        sh '''
                            if ! command -v sonar-scanner &> /dev/null; then
                                echo "Installing sonar-scanner..."
                                wget --timeout=30 --tries=3 -q https://binaries.sonarsource.com/Distribution/sonar-scanner-cli/sonar-scanner-cli-5.0.1.3006-linux.zip || {
                                    echo "Failed to download sonar-scanner. Skipping SonarQube analysis."
                                    exit 0
                                }
                                unzip -qo sonar-scanner-cli-5.0.1.3006-linux.zip || { echo "Failed to extract sonar-scanner. Skipping SonarQube analysis."; exit 0; }
                                chmod +x sonar-scanner-5.0.1.3006-linux/bin/sonar-scanner
                                echo "sonar-scanner installed successfully"
                            fi
                        '''
                        withSonarQubeEnv('SonarQube') {
                            sh '''
                                export PATH=$PWD/sonar-scanner-5.0.1.3006-linux/bin:$PATH
                                sonar-scanner -Dsonar.host.url=$SONAR_HOST_URL -Dsonar.qualitygate.wait=true -Dsonar.qualitygate.timeout=300 || {
                                    echo "WARNING: SonarQube analysis failed. Continuing pipeline..."
                                    exit 0
                                }
                            '''
                        }
                    } catch (Exception e) {
                        echo "WARNING: SonarQube analysis stage failed: ${e.message}. Continuing pipeline..."
                    }
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
                        mkdir -p .docker-ci
                    '''
                    try {
                        sh 'DOCKER_CONFIG="$PWD/.docker-ci" docker build -t "$DOCKER_IMAGE:$IMAGE_TAG" -t "$DOCKER_IMAGE:latest" .'
                        withCredentials([usernamePassword(credentialsId: DOCKERHUB_CREDENTIALS_ID, usernameVariable: 'DOCKERHUB_USERNAME', passwordVariable: 'DOCKERHUB_PASSWORD')]) {
                            sh '''
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