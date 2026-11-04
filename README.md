# Project Hub · Helm 배포 패키지 1.0.0

프로젝트 일정, 3rd-party·개발사 업무, Excel 다운로드·업로드가 포함된 웹사이트입니다.
현재 사용자 데이터·샘플 DB·비밀번호·컨테이너 이미지는 포함하지 않았습니다.
최초 실행 시 빈 DB와 관리자 계정을 만들며 이후 데이터는 PVC에 저장합니다.

## 구성

- charts/project-hub-1.0.0.tgz: 바로 설치할 수 있는 Helm Chart
- source/: 애플리케이션, Dockerfile, Helm 원본, 상세 운영 문서
- values-http.example.yaml: Ingress 없이 포트포워드로 확인
- values-https.example.yaml: 운영 HTTPS용 설정
- SHA256SUMS: 핵심 파일 무결성 확인

## 1. 컨테이너 이미지 빌드·업로드

Docker를 사용할 수 있는 PC/빌드 서버에서 실행합니다. REGISTRY는 자신의 레지스트리 주소로 바꾸세요.
Kubernetes 노드의 CPU 아키텍처에 맞게 빌드하세요. 아래는 일반 docker build 예시입니다.

```bash
REGISTRY='YOUR_REGISTRY'
docker login "$REGISTRY"
docker build -t "$REGISTRY/project-hub:1.0.0" ./source
docker push "$REGISTRY/project-hub:1.0.0"
```

Helm Chart는 이미지를 만들거나 레지스트리에 업로드하지 않습니다.

## 2. 네임스페이스·로그인 Secret

```bash
kubectl create namespace project-hub
```

k8s-secret.env 파일을 직접 만듭니다. 아래 값은 실제로 사용할 값으로 바꾸고 따옴표 없이 입력하세요.
APP_PASSWORD는 12자 이상, SESSION_SECRET은 무작위 32자 이상입니다.
SESSION_SECRET 생성 예: openssl rand -hex 32

```text
APP_PASSWORD=본인이정한12자이상비밀번호
SESSION_SECRET=본인이생성한무작위32자이상세션키
```

```bash
chmod 600 k8s-secret.env
kubectl -n project-hub create secret generic project-hub-auth --from-env-file=k8s-secret.env
```

기본 계정 ID: admin / 표시 이름: 관리자 / 비밀번호: APP_PASSWORD
다른 최초 관리자 ID·이름은 values의 admin.username, admin.name으로 설정할 수 있습니다.
새 계정 추가와 비밀번호 변경 명령은 source/README.md의 개인 계정 항목을 참고하세요.

## 3. 설치·접속 (먼저 HTTP 포트포워드로 확인)

```bash
cp values-http.example.yaml values.yaml
```

values.yaml의 image.repository를 1단계에서 사용한 레지스트리/이미지 경로로 바꾸세요.
클러스터 기본 StorageClass가 없다면 persistence.storageClass에 실제 이름을 지정하세요.
프라이빗 레지스트리는 이미지 Pull 권한이 필요합니다. 필요한 경우 네임스페이스에
이미지 Pull Secret을 만들고 imagePullSecrets: [{name: registry-secret}]를 설정하세요.

```bash
helm lint ./charts/project-hub-1.0.0.tgz -f values.yaml
helm upgrade --install projects ./charts/project-hub-1.0.0.tgz \
  -n project-hub -f values.yaml --wait --timeout 5m
kubectl -n project-hub get pods,pvc,svc
kubectl -n project-hub port-forward svc/projects-project-hub 8080:80
```

브라우저: http://localhost:8080
포트포워드 터미널을 유지한 채 기본 계정 admin으로 로그인하세요.

## 4. 운영 HTTPS로 전환

values-https.example.yaml을 복사해 레지스트리, IngressClass, 도메인, TLS Secret,
StorageClass를 실제 환경에 맞게 바꾼 뒤 같은 helm upgrade 명령으로 적용합니다.
HTTPS에서는 cookieSecure: true를 사용합니다. HTTP 테스트는 false가 필요합니다.
차트는 Ingress Controller, TLS 인증서, DNS, StorageClass, 레지스트리를 설치하지 않습니다.

## 데이터와 업데이트

- 단일 Pod / Recreate 방식이며 SQLite를 사용합니다. 여러 Pod로 늘리면 안 됩니다.
- 기본 PVC 5Gi / ReadWriteOnce. /data/project-hub.db에 DB를 저장합니다.
- 신규 빈 PVC에는 프로젝트 데이터가 없습니다. 기존 PVC를 재사용하면 기존 DB를 사용합니다.
- helm upgrade는 기존 PVC를 유지합니다. 업데이트 중 잠시 중단될 수 있습니다.
- helm uninstall projects -n project-hub 후에도 PVC는 남습니다.
- 최신 백업, 계정 관리, Docker Compose 실행법: source/README.md

## 검증 범위

Helm 3.16.4 lint, HTTP/HTTPS 템플릿 렌더링 및 리소스 연결 확인을 통과했습니다.
API/DB/인증/Excel 테스트 32개, 검토 사이트 가져오기 검증도 통과했습니다.
이 작업 환경에 Docker 실행기와 Kubernetes 클러스터가 없어 실제 이미지 빌드와
클러스터 설치는 수행하지 않았습니다. 이미지 빌드 및 PVC/레지스트리/Ingress 연결은
배포 환경에서 확인해야 합니다. 실행 데이터·검토 사이트의 브라우저 데이터는 포함하지 않았습니다.
