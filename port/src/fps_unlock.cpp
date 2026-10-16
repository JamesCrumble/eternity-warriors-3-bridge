/* Frame-rate unlock; see fps_unlock.h. */

#include <string.h>

#include "fps_unlock.h"
#include "platform.h"
#include "port_env.h"
#include "trace.h"

typedef void (*add_icall_fn)(const char *name, void *fn);
typedef void (*set_fps_fn)(int value);

static add_icall_fn g_real_add_icall = NULL;
static set_fps_fn   g_real_set_fps = NULL;
static int          g_forced_fps = -1;      /* -1: not read yet */
static volatile int g_game_called = 0;      /* the game has set a rate itself (and got ours) */

static int forced_fps()
{
    if (g_forced_fps < 0)
        g_forced_fps = (int)port_getenv_long("TARGET_FPS", 120);
    return g_forced_fps;
}

/*
 * What the guest calls instead of Application::set_targetFrameRate.
 *
 * ARM code, not Thumb: this becomes a Mono icall, and Mono's ARM JIT refuses to
 * call a Thumb address unless it believes the CPU has Thumb - which it decides
 * from /proc/cpuinfo, the host's under qemu-user ("Assertion at mini-arm.c:2644,
 * condition `thumb_supported' not met" -> abort -> the game froze at frame 60).
 */
__attribute__((target("arm"), noinline))
static ABI_ATTR void set_fps_hook(int value)
{
    int want = forced_fps();
    g_game_called = 1;
    if (want > 0 && value != want) {
        trace("fps unlock: game asked for targetFrameRate %d, forcing %d", value, want);
        value = want;
    }
    if (g_real_set_fps)
        g_real_set_fps(value);
}

/* What the guest calls instead of il2cpp_add_internal_call / mono_add_internal_call (same signature). */
static ABI_ATTR void add_icall_hook(const char *name, void *fn)
{
    if (name && !strcmp(name, "UnityEngine.Application::set_targetFrameRate") && forced_fps() > 0) {
        g_real_set_fps = (set_fps_fn)fn;
        fn = (void *)set_fps_hook;
        trace("fps unlock: hooked %s, forcing %d fps", name, forced_fps());
    }
    g_real_add_icall(name, fn);
}

extern "C" void *fps_unlock_hook_symbol(const char *name, void *sym)
{
    if (sym && name && !g_real_add_icall &&
        (!strcmp(name, "il2cpp_add_internal_call") || !strcmp(name, "mono_add_internal_call"))) {
        g_real_add_icall = (add_icall_fn)sym;
        trace("fps unlock: %s intercepted", name);
        return (void *)add_icall_hook;
    }
    return sym;
}

/*
 * Only for a game that never sets a rate itself (Shadowgun's IL2CPP build relied on this). Mono games
 * such as EW3 set it from C# early on, and calling the icall from here before Mono is up froze Unity 4.5
 * at frame 60 - so it waits much longer and is skipped once the game has called.
 */
extern "C" void fps_unlock_tick(long frame)
{
    if (frame == 600 && !g_game_called && g_real_set_fps && forced_fps() > 0) {
        trace("fps unlock: setting targetFrameRate %d", forced_fps());
        g_real_set_fps(forced_fps());
    }
}
