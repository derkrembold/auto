#!/usr/bin/env bash
# Linux/macOS counterpart of deploy.ps1: copies the mobile service to the Pi,
# optionally builds/publishes the APK and runs install.py. Never starts motors:
# install.py keeps the control server in simulation and refuses to run while a
# live driving session is active (except --logs-only, which is read-only).
#
#   ./deploy.sh                       copy files only
#   ./deploy.sh --install             copy + sudo install.py
#   ./deploy.sh --logs-only           copy + install/restart only the log service
#   ./deploy.sh --install --build-apk test, build release APK, publish on the download page
#   ./deploy.sh --host pi@192.168.0.104 ...   when motorpi.local does not resolve
#
# Host: --host, else $MOTORPI_HOST, else pi@motorpi.local.
set -euo pipefail

HOST="${MOTORPI_HOST:-pi@motorpi.local}"
INSTALL=0 LOGS_ONLY=0 ACCESS_POINT=0 BUILD_APK=0 APK_PATH=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --host) HOST="$2"; shift 2 ;;
        --install) INSTALL=1; shift ;;
        --logs-only) LOGS_ONLY=1; shift ;;
        --access-point) ACCESS_POINT=1; shift ;;
        --build-apk) BUILD_APK=1; shift ;;
        --apk) APK_PATH="$2"; shift 2 ;;
        -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$(cd "$SOURCE/../../mobile_app" && pwd)"
TARGET=/home/pi/auto/mobile
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=8 -o LogLevel=ERROR)
VERSION="$(sed -n 's/^version:[[:space:]]*//p' "$APP/pubspec.yaml" | head -n1)"

# mDNS (motorpi.local) has been flaky across repeated calls; retry like raspi/deploy.sh.
retry() {
    local attempt
    for attempt in 1 2 3; do
        "$@" && return 0
        echo "  (attempt $attempt failed, retrying...)" >&2
        sleep 1
    done
    echo "  giving up after 3 attempts: $*" >&2
    return 1
}

if [[ $BUILD_APK -eq 1 ]]; then
    (cd "$APP" && flutter pub get && flutter test && flutter build apk --release) \
        || { echo "APK build or tests failed; not deploying" >&2; exit 1; }
    APK_PATH="$APP/build/app/outputs/flutter-apk/app-release.apk"
fi

FILES=(control_core.py bridge.py wifi_server.py log_server.py motorpi-logs.service
       config.example.json motorpi-mobile.service motorpi-download.service download.html
       install.py network_policy.py commission.py live_session.py)

echo "Deploying to $HOST:$TARGET (copy only unless --install/--logs-only)"
retry ssh "${SSH_OPTS[@]}" "$HOST" "mkdir -p $TARGET"
retry scp -q "${SSH_OPTS[@]}" "${FILES[@]/#/$SOURCE/}" "$HOST:$TARGET/"

if [[ -n "$APK_PATH" ]]; then
    [[ -f "$APK_PATH" ]] || { echo "APK not found: $APK_PATH" >&2; exit 1; }
    retry ssh "${SSH_OPTS[@]}" "$HOST" \
        "mkdir -p $TARGET/download && rm -f $TARGET/ble_server.py $TARGET/dbus-motorpi.conf"
    retry scp -q "${SSH_OPTS[@]}" "$APK_PATH" "$HOST:$TARGET/download/motorpi.apk"
    echo "$VERSION" | retry ssh "${SSH_OPTS[@]}" "$HOST" "cat > $TARGET/download/version.txt"
    echo "APK $VERSION, SHA-256 $(sha256sum "$APK_PATH" | cut -d' ' -f1)"
fi

if [[ $LOGS_ONLY -eq 1 ]]; then
    retry ssh "${SSH_OPTS[@]}" "$HOST" "sudo -n python3 $TARGET/install.py --logs-only"
elif [[ $INSTALL -eq 1 ]]; then
    COMMAND="sudo -n python3 $TARGET/install.py"
    [[ $ACCESS_POINT -eq 1 ]] && COMMAND+=" --access-point"
    [[ -n "$APK_PATH" ]] && COMMAND+=" --app-download"
    # No retry: a failed install should be inspected, not repeated blindly.
    ssh "${SSH_OPTS[@]}" "$HOST" "$COMMAND" || { echo "Installation failed; inspect Pi output" >&2; exit 1; }
fi
