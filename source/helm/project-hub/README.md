# Project Hub Helm Chart

프로젝트 일정 / 3rd-party 체크리스트 / 개발사 업무 / Excel 다운로드·업로드를 제공하는 한국어 웹사이트입니다.

- 신규 설치 시 프로젝트 데이터 없이 빈 SQLite DB를 만듭니다. 최초 관리자만 생성합니다.
- Helm 패키지에는 이미지나 DB가 들어 있지 않습니다. 함께 제공한 소스로 이미지를 빌드하고 레지스트리에 push하세요.
- Kubernetes와 Helm 3, kubectl, ReadWriteOnce PVC를 제공하는 StorageClass가 필요합니다.
- APP_PASSWORD(12자 이상), SESSION_SECRET(32자 이상)를 담은 기존 Secret을 existingSecret에 지정합니다.
- 단일 Pod / Recreate / PVC 5Gi. PVC는 helm uninstall 시에도 유지합니다. 이미 데이터가 있는 PVC를 재사용하면 기존 데이터가 유지됩니다.

```bash
helm upgrade --install projects ./project-hub-1.3.1.tgz \
  -n project-hub --create-namespace \
  --set image.repository=YOUR_REGISTRY/project-hub \
  --set existingSecret=project-hub-auth \
  --set cookieSecure=false --wait --timeout 5m
kubectl -n project-hub port-forward svc/projects-project-hub 8080:80
```

접속: http://localhost:8080 / 기본 계정: admin / 비밀번호: Secret의 APP_PASSWORD. admin.username 및 admin.name은 빈 DB 최초 생성 시에만 사용합니다.

운영 HTTPS는 cookieSecure=true, ingress.enabled=true 및 자신의 IngressClass/호스트/TLS Secret을 지정합니다. Ingress Controller·인증서·레지스트리·StorageClass는 설치하지 않습니다.
