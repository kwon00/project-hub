# Project Hub · Helm 배포 패키지 1.3.1

프로젝트 일정, 3rd-party·개발사 업무, Excel 다운로드·업로드가 포함된 웹사이트입니다.
현재 사용자 데이터·샘플 DB·비밀번호·컨테이너 이미지는 포함하지 않았습니다.
최초 실행 시 빈 DB와 관리자 계정을 만들며 이후 데이터는 PVC에 저장합니다.

## 구성

- charts/project-hub-1.3.1.tgz: 바로 설치할 수 있는 Helm Chart
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
docker build -t "$REGISTRY/project-hub:1.3.1" ./source
docker push "$REGISTRY/project-hub:1.3.1"
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
helm lint ./charts/project-hub-1.3.1.tgz -f values.yaml
helm upgrade --install projects ./charts/project-hub-1.3.1.tgz \
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
API/DB/인증/Excel 테스트 42개, 검토 사이트 가져오기 검증도 통과했습니다.
이 작업 환경에 Docker 실행기와 Kubernetes 클러스터가 없어 실제 이미지 빌드와
클러스터 설치는 수행하지 않았습니다. 이미지 빌드 및 PVC/레지스트리/Ingress 연결은
배포 환경에서 확인해야 합니다. 실행 데이터·검토 사이트의 브라우저 데이터는 포함하지 않았습니다.

## 1.3.1 변경 및 기존 배포 업데이트

팝업 배경 클릭 닫기, 라이선스 정식/임시·영구·만료일, 만료 30일 이내/경과 라이선스 칸 붉은 표시, 기본 7개로 시작하고 수정 가능한 진행사항과 자유 입력 확인사항 분리, 관련 Excel 열을 반영했습니다. 확인사항은 진행률에 포함하지 않습니다.

기존 DB는 최초 실행 시 스키마 8로 자동 전환합니다. 기존 사용자 체크 항목은 확인사항으로 보존하며, 예전 기본 7개와 정확히 일치하는 목록은 새 진행사항에 옮깁니다. 배포 전 백업을 권장합니다.

GitHub에 올릴 때 charts/source/README 등 이 폴더 안의 내용물을 기존 저장소에 반영하세요. 이전 charts/project-hub-1.0.0.tgz는 기록용으로 남겨도 됩니다.

GHCR 사용 예시 (charts/source가 있는 위치):

```bash
docker build -t ghcr.io/kwon00/project-hub:1.3.1 ./source
docker push ghcr.io/kwon00/project-hub:1.3.1
helm upgrade --install projects ./charts/project-hub-1.3.1.tgz -n project-hub -f values.yaml --set image.repository=ghcr.io/kwon00/project-hub --set-string image.tag=1.3.1 --wait --timeout 5m
```

실제 컨테이너 이미지는 이 패키지에 포함되지 않았으며 GHCR에 자동 업로드되지 않습니다. 기존 배포와 같은 release/namespace 및 인증 Secret/PVC 설정을 유지하세요.

3rd-party 일반 정보 변경 후 닫기(X/취소/Esc/뒷배경)는 저장 여부를 확인합니다. 진행사항/확인사항만 바꾸면 확인창을 표시하지 않습니다. 등록된 3rd-party의 진행사항·확인사항은 자동 저장되며 일반 정보만 저장 버튼으로 반영합니다. 만료 15~30일은 연한 빨강, 14일 이내와 경과는 진한 빨강입니다. 추가 메모 표기는 메모로 변경했습니다.

1.3.1: 진행사항·확인사항 텍스트/체크/추가/삭제 자동 저장. 입력 후 약 0.5초 또는 입력칸 이동/닫기 시 반영합니다. 일반 정보 버리기를 선택해도 목록은 유지됩니다. 최초 신규 등록은 저장하기가 필요합니다. 만료 30~15일 라이선스 칸 배경색을 더 명확하게 하고, 14일 이내 색과 구분합니다. 이전 캐시를 피하도록 파일 참조 버전을 갱신했습니다.

1.3.1: 카드 배경은 유지하고 라이선스 칸만 D-30~D-15 연한 빨강, D-14부터 진한 빨강으로 표시합니다. 날짜는 D-28 / D-Day / D+28 · 만료로 구분합니다. 업체명·담당 영업·담당 엔지니어를 카드/수정/Excel에 추가하고 기존 담당자는 담당 엔지니어로 이전합니다. 카드 확인사항 추가 버튼을 제거하고 수정 버튼을 줄였습니다.

1.3.1: 영업/엔지니어별 이름·연락처·메일 별도 입력 및 카드/Excel 6열 반영. 기존 이름 유지. 연락처/메일은 선택 입력이고 저장 버튼으로 반영합니다.
