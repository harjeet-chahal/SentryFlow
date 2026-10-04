{{- define "sentryflow.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "sentryflow.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := include "sentryflow.name" . -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "sentryflow.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "sentryflow.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "sentryflow.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "sentryflow.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "sentryflow.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{- printf "%s-secrets" (include "sentryflow.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/* Fully-qualified image reference, registry optional for local builds. */}}
{{- define "sentryflow.image" -}}
{{- $root := index . 0 -}}
{{- $repo := index . 1 -}}
{{- $tag := default $root.Chart.AppVersion $root.Values.image.tag -}}
{{- if $root.Values.image.registry -}}
{{- printf "%s/%s:%s" $root.Values.image.registry $repo $tag -}}
{{- else -}}
{{- printf "%s:%s" $repo $tag -}}
{{- end -}}
{{- end -}}

{{/* Environment shared by backend and migration job. */}}
{{- define "sentryflow.backendEnv" -}}
- name: ENVIRONMENT
  valueFrom:
    configMapKeyRef:
      name: {{ include "sentryflow.fullname" . }}-config
      key: environment
- name: KAFKA_BOOTSTRAP_SERVERS
  valueFrom:
    configMapKeyRef:
      name: {{ include "sentryflow.fullname" . }}-config
      key: kafkaBootstrapServers
- name: POSTGRES_USER
  valueFrom:
    secretKeyRef:
      name: {{ include "sentryflow.secretName" . }}
      key: postgresUser
- name: POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "sentryflow.secretName" . }}
      key: postgresPassword
- name: JWT_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ include "sentryflow.secretName" . }}
      key: jwtSecret
# Assembled at runtime so the password never appears in a ConfigMap or in
# `kubectl describe` output.
- name: DATABASE_URL
  value: "postgresql://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@{{ .Values.externalServices.postgresHost }}:{{ .Values.externalServices.postgresPort }}/{{ .Values.externalServices.postgresDatabase }}"
- name: REDIS_URL
  value: "redis://{{ .Values.externalServices.redisHost }}:{{ .Values.externalServices.redisPort }}/0"
# ClickHouse backs the dashboard's analytics endpoints (read-only).
- name: CLICKHOUSE_HOST
  valueFrom:
    configMapKeyRef:
      name: {{ include "sentryflow.fullname" . }}-config
      key: clickhouseHost
- name: CLICKHOUSE_PORT
  valueFrom:
    configMapKeyRef:
      name: {{ include "sentryflow.fullname" . }}-config
      key: clickhousePort
- name: CLICKHOUSE_DATABASE
  valueFrom:
    configMapKeyRef:
      name: {{ include "sentryflow.fullname" . }}-config
      key: clickhouseDatabase
- name: CLICKHOUSE_USER
  valueFrom:
    secretKeyRef:
      name: {{ include "sentryflow.secretName" . }}
      key: clickhouseUser
- name: CLICKHOUSE_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "sentryflow.secretName" . }}
      key: clickhousePassword
{{- range $key, $value := dict "LOG_LEVEL" "logLevel" "CORS_ORIGINS" "corsOrigins" "DEFAULT_RATE_LIMIT" "defaultRateLimit" "DEFAULT_RATE_LIMIT_WINDOW" "defaultRateLimitWindow" "DEFAULT_RATE_LIMIT_ALGORITHM" "defaultRateLimitAlgorithm" "DEFAULT_BURST_CAPACITY" "defaultBurstCapacity" "RATE_LIMIT_FAIL_OPEN" "rateLimitFailOpen" "ACCESS_TOKEN_EXPIRE_MINUTES" "accessTokenExpireMinutes" "REFRESH_TOKEN_EXPIRE_DAYS" "refreshTokenExpireDays" "GATEWAY_TOKEN_EXPIRE_MINUTES" "gatewayTokenExpireMinutes" }}
- name: {{ $key }}
  valueFrom:
    configMapKeyRef:
      name: {{ include "sentryflow.fullname" $ }}-config
      key: {{ $value }}
{{- end }}
{{- end -}}
