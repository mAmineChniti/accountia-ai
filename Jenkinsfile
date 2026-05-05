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
                    python3.11 -m venv venv
                    ./venv/bin/python -m pip install --upgrade pip
                    ./venv/bin/python -m pip install -r requirements.txt coverage
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
                    ./venv/bin/coverage run -m pytest tests/ -v
                    ./venv/bin/coverage xml -o coverage.xml
                    ./venv/bin/coverage report
                '''
            }
        }

        stage('SonarQube Analysis') {
            steps {
                sh 'sonar-scanner -Dsonar.qualitygate.wait=true -Dsonar.qualitygate.timeout=300'
            }
        }

        stage('Build') {
            steps {
                sh './venv/bin/python -c "from app.main import app; print(\'✓ App builds successfully\')"'
            }
        }

        stage('Docker Build & Push') {
            steps {
                script {
                    sh 'docker build -t "$DOCKER_IMAGE:$IMAGE_TAG" -t "$DOCKER_IMAGE:latest" .'
                    withCredentials([usernamePassword(credentialsId: DOCKERHUB_CREDENTIALS_ID, usernameVariable: 'DOCKERHUB_USERNAME', passwordVariable: 'DOCKERHUB_PASSWORD')]) {
                        sh '''
                            echo "$DOCKERHUB_PASSWORD" | docker login -u "$DOCKERHUB_USERNAME" --password-stdin
                            docker push "$DOCKER_IMAGE:$IMAGE_TAG"
                            docker push "$DOCKER_IMAGE:latest"
                        '''
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
            sh 'rm -rf .pytest_cache .coverage coverage.xml || true'
            sh 'docker logout || true'
        }
    }
}