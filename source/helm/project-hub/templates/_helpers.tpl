{{- define "project-hub.fullname" -}}
{{- printf "%s-project-hub" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- define "project-hub.selectorLabels" -}}
app.kubernetes.io/name: project-hub
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
{{- define "project-hub.labels" -}}
{{ include "project-hub.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}
