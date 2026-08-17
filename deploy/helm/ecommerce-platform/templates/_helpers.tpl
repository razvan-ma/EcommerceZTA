{{- define "ecommerce-platform.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "ecommerce-platform.labels" -}}
app.kubernetes.io/name: {{ include "ecommerce-platform.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}
