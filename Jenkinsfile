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
                    python3 -m pip install --upgrade pip
                    python3 -m pip install -r requirements.txt
                    python3 -m pip install coverage
                '''
            }
        }

        stage('Lint') {
            steps {
                sh 'ruff check app/'
            }
        }

        stage('Format') {
            steps {
                sh 'ruff format --check app/'
            }
        }

        stage('Tests') {
            steps {
                sh '''
                    coverage run -m pytest tests/ -v
                    coverage xml -o coverage.xml
                    coverage report
                '''
            }
        }

        stage('SonarQube Analysis') {
            steps {
                sh 'sonar-scanner'
            }
        }

        stage('Build') {
            steps {
                sh 'python3 -c "from app.main import app; print(\'✓ App builds successfully\')"'
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
            sh 'rm -rf .pytest_cache .coverage coverage.xml || true'
            sh 'docker logout || true'
        }
    }
}