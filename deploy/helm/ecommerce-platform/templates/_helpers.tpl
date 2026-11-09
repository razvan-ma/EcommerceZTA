{{- define "ecommerce-platform.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "ecommerce-platform.labels" -}}
app.kubernetes.io/name: {{ include "ecommerce-platform.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
Base64 password for a generated Secret. Reuses the value already stored in the
cluster so upgrades never rotate a password that an initialized database or a
running workload depends on; otherwise generates a fresh random one.
Usage: include "ecommerce-platform.password" (dict "ctx" $ "name" "secret-name")
*/}}
{{- define "ecommerce-platform.password" -}}
{{- $existing := lookup "v1" "Secret" .ctx.Release.Namespace .name -}}
{{- if and $existing $existing.data (hasKey $existing.data "password") -}}
{{- index $existing.data "password" -}}
{{- else -}}
{{- randAlphaNum 32 | b64enc -}}
{{- end -}}
{{- end -}}

{{/* PostgreSQL role and schema name for a service ("order" is a reserved word). */}}
{{- define "ecommerce-platform.dbRole" -}}
svc_{{ . }}
{{- end -}}
