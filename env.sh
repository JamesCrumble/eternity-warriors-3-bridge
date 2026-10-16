#!/usr/bin/env bash
# Source this from the repository root: `source env.sh`. Touches only the current shell.
_P="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
export EW3_PROBE="$_P"
export EW3_REPO="$_P/port"
export EW3_GAMEDIR="$_P/ew3data"
export JAVA_HOME="$_P/jdk"
export ANDROID_HOME="$_P/android-sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export PKG_CONFIG_PATH="$_P/sdl-arm/lib/pkgconfig"
export DOTNET_ROOT="$_P/dotnet"
export DOTNET_CLI_HOME="$_P/dotnet/home"
export NUGET_PACKAGES="$_P/dotnet/nuget"
export DOTNET_CLI_TELEMETRY_OPTOUT=1
export DOTNET_NOLOGO=1
export BOOST_ROOT="$_P/third_party/boost"
export PATH="$DOTNET_ROOT:$DOTNET_ROOT/tools:$JAVA_HOME/bin:$ANDROID_HOME/build-tools/34.0.0:$PATH"
unset _P
