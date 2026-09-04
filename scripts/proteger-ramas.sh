#!/usr/bin/env bash
# Aplica las protecciones de las tres ramas. Lo corre una vez alguien con
# permiso de admin sobre el repositorio:  ./scripts/proteger-ramas.sh
#
# Las reglas están en docs/RAMAS.md; esto sólo las escribe en GitHub.
set -euo pipefail

REPO="${1:-desarrollo557/BOT_PDF}"

# Los nombres tienen que coincidir con los `name:` de los jobs en
# .github/workflows/, que es como GitHub los reporta.
CHECKS_BASE='"Arquitectura (dirección de las dependencias)","Backend (pytest)","Front (check, pruebas, build)","Base de datos (el esquema levanta)"'
CHECK_PR='"Rama, título y descripción"'

proteger() {
  local rama="$1" revisiones="$2" checks="$3"
  echo "── $rama (revisiones requeridas: $revisiones)"
  gh api -X PUT "repos/$REPO/branches/$rama/protection" \
    --input - <<JSON
{
  "required_status_checks": { "strict": true, "contexts": [$checks] },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": $revisiones,
    "dismiss_stale_reviews": true,
    "require_last_push_approval": false
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON
}

proteger develop    0 "$CHECKS_BASE,$CHECK_PR"
proteger main       1 "$CHECKS_BASE,$CHECK_PR"
proteger produccion 1 "$CHECKS_BASE,$CHECK_PR"

echo
echo "Listo. Ninguna de las tres ramas acepta push directo."
