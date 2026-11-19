#!/usr/bin/env bash
# Source this from the repository root: `source env.sh`. Touches only the current shell.
_P="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# Third-party toolchains/dependencies: looked up inside this project first (jdk/, android-sdk/, ...), then in ../__shared-third-party__
export SHARED_3P="$(cd "$_P/../__shared-third-party__" 2>/dev/null && pwd || echo "$_P/../__shared-third-party__")"
_tp() { if [ -e "$_P/${2:-$1}" ]; then echo "$_P/${2:-$1}"; else echo "$SHARED_3P/$1"; fi; }
export EW3_PROBE="$_P"
export EW3_REPO="$_P/port"
export EW3_GAMEDIR="$_P/ew3data"
export JAVA_HOME="$(_tp jdk)"
export ANDROID_HOME="$(_tp android-sdk)"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export PKG_CONFIG_PATH="$(_tp sdl-arm)/lib/pkgconfig"
export DOTNET_ROOT="$(_tp dotnet)"
export DOTNET_CLI_HOME="$DOTNET_ROOT/home"
export NUGET_PACKAGES="$DOTNET_ROOT/nuget"
export DOTNET_CLI_TELEMETRY_OPTOUT=1
export DOTNET_NOLOGO=1
export BOOST_ROOT="$(_tp boost third_party/boost)"
export PATH="$DOTNET_ROOT:$DOTNET_ROOT/tools:$JAVA_HOME/bin:$ANDROID_HOME/build-tools/34.0.0:$PATH"
unset -f _tp
unset _P
