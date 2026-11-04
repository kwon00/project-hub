# Project Hub

프로젝트별 일정과 3rd-party·개발사 정보을 관리하는 자체 호스팅 웹 애플리케이션입니다. 소스 코드, Dockerfile, Docker Compose, Helm 차트가 포함되어 있습니다.

## 제공 기능

- 프로젝트 등록·수정·삭제, 고객사·담당자·기간·상태·설명 관리
- 일정·개발사 업무 관리와 이름별 3rd-party 설치 일자·개발사 적용 완료·우선순위·진행률·진행사항 체크리스트 관리
- 전체 대시보드, 지연 업무, 7일 내 마감 업무, 프로젝트 평균 진행률
- 월별 달력 및 목록, 날짜별 전체 업무 조회
- 프로젝트/3rd-party/개발사 검색, 상태 및 프로젝트 필터
- 변경 이력, 화면별 Excel(.xlsx) 다운로드: 전체 일정 / 단일 프로젝트 / 단일 프로젝트 3rd-party/개발사
- 프로젝트 Excel 5개 시트: 개요 / 일정 / 3rd-party / 개발사 / 변경이력
- 개인 계정(ID·이름) 및 비밀번호 로그인, 12시간 세션, SQLite 영구 저장

UI는 한국어이며 마감일 판정 및 화면의 활동 시각은 한국 시간을 기준으로 합니다. 변경 이력은 화면에서 전체 최근 500건까지 조회하며 Excel에는 해당 범위의 전체 이력을 내보냅니다. 대시보드와 프로젝트 목록에는 다운로드 버튼이 없습니다. 전체 일정 메뉴는 전체 기간의 일정·개발사 업무 및 입력된 3rd-party 설치 일자만 하나의 `일정` 시트로 내보냅니다. 프로젝트 상세는 선택한 프로젝트의 5개 시트만, 프로젝트 3rd-party·개발사 탭의 별도 버튼은 각각 해당 프로젝트의 3rd-party 또는 개발사 시트만 내보냅니다. 3rd-party·개발사 전체 현황의 버튼은 각각 해당 항목만 내보냅니다. 검색어·상태 필터는 Excel 범위에 적용하지 않습니다. 프로젝트 상세에서 새 업무를 등록할 때 프로젝트는 현재 프로젝트로 고정됩니다.

## 빠르게 실행: Docker Compose

준비: Docker Engine 및 Docker Compose v2.

```bash
cp .env.example .env
# .env의 APP_PASSWORD와 SESSION_SECRET을 본인 값으로 변경
# SESSION_SECRET 생성 예:
python3 -c 'import secrets; print(secrets.token_hex(32))'

docker compose up -d --build
```

브라우저에서 **http://localhost:8080** 접속 → 계정 ID **admin**, `.env`에 설정한 초기 `APP_PASSWORD`로 로그인합니다. 첫 시작 시 DB에 초기 관리자 계정을 생성하고 이후에는 DB의 개인 계정으로 인증합니다. 비밀번호는 12자 이상, 세션 키는 무작위 32자 이상이어야 합니다. `.env.example`의 예시 값은 사용 전 교체하세요.

기본 포트 바인딩은 `127.0.0.1:8080`입니다. 원격 서버에서 확인할 때는 SSH 터널을 이용하거나 HTTPS 역방향 프록시를 구성하세요.

```bash
ssh -L 8080:127.0.0.1:8080 user@server
```

Compose는 로컬 HTTP 확인용으로 `COOKIE_SECURE=false`를 사용합니다. 운영 HTTPS 프록시 뒤에서는 `COOKIE_SECURE=true`로 변경하고 HTTPS로 접속하세요. TLS 종료 위치는 Ingress 또는 외부 프록시입니다.

```bash
docker compose logs -f project-hub
docker compose down           # 데이터 볼륨 유지
# docker compose down -v 는 DB 볼륨까지 삭제하므로 사용에 주의
```

## Kubernetes / Helm 배포

준비: Kubernetes, Helm 3, `kubectl`, PVC를 제공하는 StorageClass, 컨테이너 레지스트리. 외부 HTTPS 접속에는 Ingress Controller 및 TLS 인증서가 필요합니다. 차트는 특정 Ingress 제품에 종속되지 않습니다.

### 1. 이미지 빌드 및 레지스트리 업로드

`REGISTRY`를 Azure ACR 또는 SCP Container Registry 주소로 바꿉니다.

```bash
REGISTRY='YOUR_REGISTRY'
docker login "$REGISTRY"
docker build -t "$REGISTRY/project-hub:1.0.0" .
docker push "$REGISTRY/project-hub:1.0.0"
```

빌드 머신과 노드 CPU 아키텍처가 다르면 `docker buildx build --platform linux/amd64 --push -t ... .` 등 대상 아키텍처에 맞게 빌드하세요.

### 2. 네임스페이스와 로그인 Secret 생성

```bash
kubectl create namespace project-hub
```

Secret 전용 파일 `k8s-secret.env`를 작성합니다. 이 파일은 **따옴표 없이** 아래 2개 키만 포함해야 합니다. 값을 본인의 값으로 바꾸세요. Compose용 `.env`를 그대로 사용하면 따옴표까지 비밀번호에 포함될 수 있습니다.

```text
APP_PASSWORD=본인이설정한12자이상비밀번호
SESSION_SECRET=생성한무작위32자이상세션키
```

```bash
chmod 600 k8s-secret.env
kubectl -n project-hub create secret generic project-hub-auth --from-env-file=k8s-secret.env
```

Secret 전용 파일은 저장소에 커밋하지 마세요. 이미 존재하는 Secret은 관리 정책에 맞춰 갱신하세요.

프라이빗 레지스트리 인증이 필요한 경우 `imagePullSecrets`에 기존 docker-registry Secret 이름을 설정합니다. ACR에 대한 AKS 통합 권한 등이 이미 설정된 경우 별도 Secret이 필요하지 않을 수 있습니다.

### 3. 운영 values 작성

`docs/values-production.example.yaml`을 복사하여 레지스트리, StorageClass, 호스트, IngressClass와 TLS Secret을 자신의 환경에 맞게 바꿉니다.

```bash
cp docs/values-production.example.yaml values-production.yaml
helm lint ./helm/project-hub -f values-production.yaml
helm template projects ./helm/project-hub -n project-hub -f values-production.yaml > /tmp/project-hub-rendered.yaml
helm upgrade --install projects ./helm/project-hub \
  -n project-hub -f values-production.yaml --wait --timeout 5m
kubectl -n project-hub get pods,pvc,svc,ingress
```

`ingress.host`의 DNS가 Ingress 주소를 가리켜야 하며 해당 호스트에 유효한 TLS Secret을 미리 생성해야 합니다. 차트가 Ingress Controller, DNS 또는 인증서를 자동 생성하지는 않습니다.

차트 `.tgz`를 사용해도 동일합니다.

```bash
helm upgrade --install projects ./project-hub-1.0.0.tgz \
  -n project-hub -f values-production.yaml --wait --timeout 5m
```

### Ingress 없이 먼저 확인

```bash
helm upgrade --install projects ./helm/project-hub -n project-hub \
  --set image.repository=YOUR_REGISTRY/project-hub \
  --set existingSecret=project-hub-auth \
  --set cookieSecure=false --wait --timeout 5m
kubectl -n project-hub port-forward svc/projects-project-hub 8080:80
```

http://localhost:8080 에서 로그인합니다. 실제 HTTPS 운영으로 전환할 때는 `cookieSecure=true`로 복구하세요. 차트의 기본값은 HTTPS용 `true`입니다.

## 데이터 보관 및 운영 범위

- DB: `/data/project-hub.db`, 컨테이너 재생성 후에도 Compose volume 또는 Kubernetes PVC에 유지됩니다.
- 기본 PVC 5Gi, `ReadWriteOnce`. 기본 StorageClass 또는 `persistence.storageClass`에 지정한 클래스를 사용합니다.
- **단일 Pod / 단일 프로세스 / Recreate 배포**입니다. 이미지 업데이트 중 잠시 중단됩니다. SQLite 파일을 여러 Pod에서 공유하거나 replicas를 늘리지 마세요.
- 사용자별 ID·이름·비밀번호로 로그인합니다. 인증된 모든 계정은 동일한 프로젝트를 공동 관리합니다. 역할별 권한, SSO, 협력사별 데이터 분리와 담당자별 접근 제어는 포함하지 않습니다.
- 같은 항목을 동시에 수정하면 마지막 저장 내용이 적용됩니다. 변경 이력에는 서버가 인증한 계정 ID와 당시 이름을 저장하며 이름 변경 후에도 과거 기록을 유지합니다. 계정 이름은 사용자가 업무 입력 시 임의로 지정하지 못합니다. 이전 버전의 기록은 작성자가 없으므로 `기록 없음 (기존 데이터)`으로 표시합니다.
- 3rd-party는 이름으로 등록하고 하위 진행사항을 체크리스트로 관리합니다. 체크하면 취소선이 생기고 해제하면 복구됩니다. 설치 일자는 미정으로 비워 둘 수 있으며, 개발사 적용 완료는 별도 체크로 관리합니다. 3rd-party 진행률은 완료 항목 수 ÷ 전체 항목 수 × 100을 정수 반올림하여 자동 계산합니다. 항목이 없으면 0%, 전부 완료하면 100%입니다. 추가·삭제·수정·체크 해제 시에도 다시 계산하며 Excel과 프로젝트 평균에 같은 값을 반영합니다. 외부 시스템/API와 자동 연동하지 않습니다.
- 첨부파일과 알림 발송은 제공하지 않습니다. Excel 다운로드는 보고용이며 DB 전체 백업을 대체하지 않습니다.
- 진행률은 업무별 진행률의 단순 평균입니다. 업무가 없으면 0%입니다. 완료 상태는 자동으로 100%가 되며 프로젝트 자체 상태는 별도로 관리합니다.
- 차트 삭제 시 PVC를 남기도록 `helm.sh/resource-policy: keep`을 설정했습니다. 이 설정은 클러스터/스토리지 장애 또는 수동 삭제에 대한 백업을 대체하지 않습니다.

## 백업과 복구

SQLite의 온라인 백업 API를 사용합니다. 실행 중인 DB의 `.db` 파일만 그대로 복사하면 WAL 변경분을 놓칠 수 있습니다.

### Compose 백업

```bash
mkdir -p backups
docker compose exec project-hub python scripts/backup.py /tmp/project-hub-backup.db
docker compose cp project-hub:/tmp/project-hub-backup.db ./backups/project-hub-backup.db
docker compose exec project-hub rm /tmp/project-hub-backup.db
```

백업 파일은 별도 안전한 스토리지에 보관하세요. 동일한 이름이 존재하면 백업 도구는 덮어쓰지 않습니다.

### Kubernetes 백업

```bash
POD=$(kubectl -n project-hub get pod -l app.kubernetes.io/instance=projects -o jsonpath='{.items[0].metadata.name}')
kubectl -n project-hub exec "$POD" -- python scripts/backup.py /tmp/project-hub-backup.db
kubectl -n project-hub cp "$POD":/tmp/project-hub-backup.db ./project-hub-backup.db
kubectl -n project-hub exec "$POD" -- rm /tmp/project-hub-backup.db
```

### 복구

1. 복구 전 현재 DB도 백업합니다.
2. Compose 서비스를 중지하거나 Kubernetes Deployment를 `replicas=0`으로 내려 DB 쓰기를 중단합니다.
3. Compose의 데이터 볼륨 또는 동일 PVC를 임시 유지보수 컨테이너/Pod에 연결합니다.
4. 데이터 경로의 기존 `project-hub.db`, `project-hub.db-wal`, `project-hub.db-shm`을 별도로 보관한 뒤 제거합니다. 검증한 백업을 `project-hub.db`로 복사합니다.
5. 파일 소유권을 `10001:10001`, 쓰기 가능한 권한으로 맞춘 뒤 유지보수 컨테이너/Pod를 제거합니다.
6. 앱을 다시 시작하거나 Deployment를 `replicas=1`로 복구하고 데이터를 확인합니다.

## 개인 계정과 변경 이력

최초 시작 시 초기 관리자 계정 `admin` / 이름 `관리자`를 DB에 만듭니다. 초기 비밀번호는 `APP_PASSWORD`입니다. DB에 계정이 이미 있으면 재시작할 때 생성하거나 덮어쓰지 않습니다. 초기 계정 ID/이름은 최초 실행 전 `APP_ADMIN_USERNAME`과 `APP_ADMIN_NAME` 환경변수로 지정할 수도 있습니다.

개인 계정은 운영자가 앱 컨테이너의 CLI에서 추가합니다. 비밀번호는 명령행 인자에 쓰지 않고 비공개 입력 프롬프트로 설정합니다.

```bash
# Compose: 계정 목록 / 사용자 추가 / 이름 변경
docker compose exec project-hub python scripts/users.py list
docker compose exec project-hub python scripts/users.py add user01 --name '홍길동'
docker compose exec project-hub python scripts/users.py rename admin --name '관리 담당자'
# 비밀번호 재설정 / 계정 비활성화
docker compose exec project-hub python scripts/users.py password user01
docker compose exec project-hub python scripts/users.py disable user01
```

Kubernetes는 `kubectl -n project-hub exec -it deploy/projects-project-hub -- python scripts/users.py ...` 형식으로 동일하게 실행합니다. 비활성 계정은 `enable`로 복구할 수 있습니다. 계정 비활성화 및 비밀번호 재설정 시 해당 계정의 기존 세션은 즉시 만료됩니다. 비밀번호는 salt가 있는 PBKDF2 해시로 DB에 보관합니다.

**APP_PASSWORD 환경변수 변경은 이미 생성된 계정의 비밀번호를 바꾸지 않습니다.** 위 CLI를 이용하세요. `SESSION_SECRET`을 바꾸고 Compose 컨테이너 재생성 또는 Kubernetes Pod 재시작을 하면 모든 계정의 세션이 만료됩니다. DB 백업에는 사용자 계정과 해시도 포함되므로 백업 파일을 안전하게 보관하세요.

기존 버전에서 처음 업그레이드하면 이력 작성자 컬럼과 계정 테이블을 추가하고 초기 계정을 만듭니다. 기존 프로젝트·일정·메모는 유지합니다. 기존 공유 로그인 세션은 만료되므로 ID와 비밀번호로 다시 로그인하세요. 업그레이드 전 백업하세요.

## 개발 및 테스트

Python 3.12 권장. Node 빌드나 외부 CDN은 필요하지 않습니다. 운영 컨테이너는 `requirements.lock`으로 확인된 전체 Python 의존성 버전을 고정합니다.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
# 개발용 환경변수 설정: 본인의 임시 값 사용
export APP_PASSWORD='your-local-development-password'
export SESSION_SECRET='your-random-development-secret-at-least-32-characters'
export COOKIE_SECURE=false
export DB_PATH="$PWD/local-data/project-hub.db"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
python -m unittest discover -s tests -v
node --check app/static/app.js
```


`tests/test_app.py`는 테스트용 비밀번호/세션 키와 임시 DB를 사용합니다. 운영 DB를 열지 않습니다.

## 파일 구성

```text
app/main.py                         API · 인증 · DB · Excel 생성
app/static/                         한국어 웹 UI
Dockerfile                          비루트 사용자 실행 이미지
compose.yaml                        로컬 컨테이너 실행
helm/project-hub/                   Helm 차트 원본
docs/values-production.example.yaml 운영 배포 예시
scripts/backup.py                   온라인 DB 백업
scripts/users.py                    개인 계정 추가·변경
scripts/smoke_test.sh               실행된 서버 기본 점검
tests/test_app.py                   API / DB / 인증 / Excel 검증
```

제작 환경의 검증 결과와 한계는 `docs/VALIDATION.md`를 참고하세요.

## Excel 형식 및 기존 데이터 전환

- 파일명: `프로젝트이름_항목_YYYY-MM-DD.xlsx` (한국 날짜). 예: `클라우드 인프라 구축_3rd-party_2026-11-04.xlsx`.
- 전체 메뉴에서는 프로젝트 이름 대신 `전체프로젝트`를 사용합니다. 파일명에 사용할 수 없는 문자는 `_`로 치환합니다.
- 프로젝트 Excel의 시트 순서는 정확히 `개요 / 일정 / 3rd-party / 개발사 / 변경이력`입니다.
- 날짜·진행률·헤더·텍스트 등 모든 셀을 위쪽 정렬합니다. 날짜와 진행률은 Excel 숫자 타입을 유지합니다.
- 3rd-party 시트에는 이름, 설치 일자, 개발사 적용 완료, 우선순위, 진행률 및 진행사항을 내보냅니다. 완료한 진행사항은 ● 표시와 취소선, 미완료 항목은 ○ 표시를 사용합니다.
- 기존 `partner` 자료는 최초 실행 때 `third_party`로 전환합니다. ID·기간·진행률·원래 메모는 보존하며, 기존 업체명을 이름으로, 기존 제목과 메모를 하위 진행사항으로 옮깁니다. 기존 기간을 실제 설치 일자로 추정하지 않습니다.
- 미리보기의 브라우저 저장 자료도 기존 키를 유지하여 전환합니다. 개발사 탭에는 별도 업무를 등록합니다.
- 업그레이드 전 DB를 백업하세요. 신규 컬럼은 `installed_at`, `developer_applied`, `checklist`이며 DB 스키마 버전은 4입니다.

### 새 3rd-party의 기본 진행사항

새 등록 시 다음 7개 항목을 미완료 상태로 넣습니다. 각 항목은 수정·삭제할 수 있으며 항목 추가도 가능합니다. 기존 항목과 의도적으로 비운 체크리스트에는 기본 항목을 덮어쓰지 않습니다.

1. 업체 컨택하기
2. 설치 일자 확정
3. 설치 전 구성 확인(OS, 디스크, 스펙, 특이사항 등)
4. 솔루션 설치 파일 수신
5. 솔루션 적용 완료
6. 매뉴얼/가이드 수신
7. 구축 완료 보고서 수신

### 프로젝트 색상

프로젝트 생성·설정에서 팔레트 또는 직접 색상을 선택합니다. 색상은 `#RRGGBB` 형식으로 저장합니다. 전체 일정의 일정·개발사 업무·3rd-party 설치 표시는 해당 프로젝트의 색상을 사용하고, 범례와 목록의 프로젝트 표시에서도 확인할 수 있습니다. 기존 프로젝트는 기본 초록색으로 전환되며 설정에서 변경할 수 있습니다. 프로젝트 색상을 바꿔도 일정 자체를 수정할 필요 없이 모든 연결 일정에 반영됩니다.

## Excel 업로드

- 프로젝트 목록, 전체 일정, 프로젝트 상세의 `Excel 업로드`에서 내려받은 `.xlsx` 양식을 선택합니다. 시트명과 열 제목을 유지하세요. 최대 10MB / 데이터 2,000행을 지원합니다. 수식은 값으로 바꿔 저장하세요.
- 개요·일정·3rd-party·개발사 시트를 읽고 변경이력 등 다른 시트는 제외합니다. 미리보기에서 추가·수정·동일 건수를 확인한 뒤 `반영하기`를 누르면 저장합니다. 오류가 있으면 시트·행을 안내하고 전체 반영을 취소합니다. 미리보기 뒤 데이터가 바뀌면 다시 확인해야 합니다.
- 최신 양식의 숨김 식별 열은 기존 행을 찾는 데 사용하므로 유지하세요. 새 항목은 새 빈 행에 작성하세요. 식별 열이 없는 기존 양식은 프로젝트명과 항목명(개발사는 개발사명 포함)으로 기존 행을 찾으며 중복 이름이 있으면 반영하지 않습니다. Excel에서 행을 지워도 웹 항목은 삭제되지 않습니다.
- 프로젝트 상세 업로드는 현재 프로젝트에만 반영됩니다. 프로젝트 목록에서 신규 프로젝트를 가져오려면 개요 시트도 작성하세요. 기존 프로젝트 색은 유지합니다.
- 3rd-party 진행사항은 한 셀에서 줄바꿈하여 `● 완료한 내용` / `○ 미완료 내용`으로 작성하세요. 진행률 열 대신 체크 상태에서 진행률을 다시 계산합니다. 예전 ☑ 표시도 읽습니다.
- 변경 이력에는 가져오기를 실행한 로그인 계정이 기록됩니다. 업로드 원본 파일은 보관하지 않습니다.
- 검토 사이트는 현재 브라우저에 저장하며 컨테이너 버전은 인증된 API를 통해 SQLite에 트랜잭션으로 저장합니다.

### 빈 필수값 가져오기와 개발사 날짜

- 개발사 시작일·마감일은 UI와 API에서 선택 입력입니다. 한쪽만 입력할 수 있으며 양쪽을 입력하면 시작일 ≤ 마감일이어야 합니다. 날짜 없는 업무는 개발사 목록에 표시되고, 한 날짜만 있으면 달력에는 해당 날짜에 표시합니다.
- Excel에서는 프로젝트명·업무명·개발사명·필수 날짜가 비어 있어도 우선 저장할 수 있습니다. 이름이 없으면 화면에 미입력으로 표시합니다. 이후 UI에서 저장할 때 프로젝트명/프로젝트 기간, 업무명, 일정 기간, 개발사명 등 해당 유형의 필수값을 모두 검사합니다. 개발사 날짜는 계속 선택 입력입니다.
- 시트와 열 제목, 반영 대상 프로젝트 식별은 필요합니다. 프로젝트 상세에서는 현재 프로젝트로 고정됩니다. 형식 오류·잘못된 날짜 범위·다른 프로젝트 데이터·중복 식별자는 계속 차단합니다.
