/*
 * ew3gl module 7/12: keyboard and mouse -> the game's touch controls.
 *
 * The game knows only touches (a floating joystick on the left half, buttons on
 * the right), so the PC controls are translated here, on the host; the game and
 * the guest port are untouched and the Android build is unaffected.
 *
 *   EW3_GL_KEYMAP=1 (default) / 0     on / off (off: the mouse is one finger, Esc = BACK)
 *   WASD or arrows   the joystick: a finger goes down in the joystick zone and moves
 *                    towards the pressed keys
 *   F1               mouse mode: "touch" (the cursor is a finger - menus) or
 *                    "battle" (LMB = attack button, RMB = skill 1)
 *   J / Enter        attack;   1..4  skills;   Space  dodge;   Esc  BACK
 *
 * Button positions are fractions of the screen (x right, y down). The defaults
 * are the attack button and guesses for the rest; <control dir>/keymap.txt
 * overrides them, one "name x y" per line (names: joystick attack skill1..skill4
 * dodge; joystick also takes a third number, the drag radius).
 */
enum { BTN_ATTACK, BTN_SKILL1, BTN_SKILL2, BTN_SKILL3, BTN_SKILL4, BTN_DODGE, BTN_COUNT };
static const char *const kBtnNames[BTN_COUNT] = { "attack", "skill1", "skill2", "skill3", "skill4", "dodge" };
static float g_btn[BTN_COUNT][2] = {
    { 0.906f, 0.806f },   /* attack: measured on a 1280x720 frame */
    { 0.760f, 0.880f }, { 0.790f, 0.680f }, { 0.880f, 0.560f }, { 0.700f, 0.720f },   /* guesses */
    { 0.960f, 0.560f },
};
static int g_btn_down[BTN_COUNT];
static float g_joy[3] = { 0.08f, 0.86f, 0.08f };   /* centre x, y, drag radius (of the height): bottom-left corner, out of the way */
static int g_keymap_on = -1, g_mouse_battle;

/* Joystick state: what the keys want, and what was last sent. */
static int g_joy_down, g_joy_wait;
static float g_joy_want[2], g_joy_sent[2];

/* Finger ids: 0 the mouse, 1 the joystick, 2.. one per button. */
#define FINGER_JOY 1
#define FINGER_BTN(b) (2 + (b))

static void input_load_keymap(void)
{
    g_keymap_on = (int)cfg_long("GL_KEYMAP", 1) != 0;
    if (!g_cfg.control_dir)
        return;
    char path[1024], line[256], name[64];
    snprintf(path, sizeof(path), "%s/keymap.txt", g_cfg.control_dir);
    FILE *f = fopen(path, "r");
    if (!f)
        return;
    while (fgets(line, sizeof(line), f)) {
        float x, y, r = 0;
        int n = sscanf(line, "%63s %f %f %f", name, &x, &y, &r);
        if (n < 3 || name[0] == '#')
            continue;
        if (!strcmp(name, "joystick")) {
            g_joy[0] = x, g_joy[1] = y;
            if (n == 4)
                g_joy[2] = r;
            continue;
        }
        for (int b = 0; b < BTN_COUNT; b++)
            if (!strcmp(name, kBtnNames[b]))
                g_btn[b][0] = x, g_btn[b][1] = y;
    }
    fclose(f);
    glog("keymap: %s loaded", path);
}

static void btn_press(int b, int down)
{
    if (g_btn_down[b] == down)
        return;
    g_btn_down[b] = down;
    control_cmd("touch %d %.0f %.0f %d\n", down ? 1 : 0, g_btn[b][0] * g_cfg.width, g_btn[b][1] * g_cfg.height,
                FINGER_BTN(b));
}

/* The direction the movement keys ask for, unit length or zero. */
static void joy_from_keys(void)
{
    const Uint8 *k = SDL_GetKeyboardState(NULL);
    float x = (float)((k[SDL_SCANCODE_D] || k[SDL_SCANCODE_RIGHT]) - (k[SDL_SCANCODE_A] || k[SDL_SCANCODE_LEFT]));
    float y = (float)((k[SDL_SCANCODE_S] || k[SDL_SCANCODE_DOWN]) - (k[SDL_SCANCODE_W] || k[SDL_SCANCODE_UP]));
    if (x && y)
        x *= 0.7071f, y *= 0.7071f;
    g_joy_want[0] = x, g_joy_want[1] = y;
}

/*
 * Once per presented frame. The joystick centres itself where the finger lands,
 * so the drag goes out two frames after the touch-down: sent together, the game
 * would see the finger land on the dragged spot and read no direction at all.
 */
static void input_frame(void)
{
    if (g_keymap_on <= 0)
        return;
    joy_from_keys();
    int want = g_joy_want[0] != 0 || g_joy_want[1] != 0;
    float cx = g_joy[0] * g_cfg.width, cy = g_joy[1] * g_cfg.height, r = g_joy[2] * g_cfg.height;
    if (want && !g_joy_down) {
        control_cmd("touch 1 %.0f %.0f %d\n", cx, cy, FINGER_JOY);
        g_joy_down = 1, g_joy_wait = 2;
        g_joy_sent[0] = g_joy_sent[1] = 0;
    } else if (g_joy_down && g_joy_wait > 0) {
        g_joy_wait--;
    } else if (g_joy_down && want &&
               (g_joy_want[0] != g_joy_sent[0] || g_joy_want[1] != g_joy_sent[1])) {
        control_cmd("touch 2 %.0f %.0f %d\n", cx + g_joy_want[0] * r, cy + g_joy_want[1] * r, FINGER_JOY);
        g_joy_sent[0] = g_joy_want[0], g_joy_sent[1] = g_joy_want[1];
    } else if (g_joy_down && !want) {
        control_cmd("touch 0 %.0f %.0f %d\n", cx + g_joy_sent[0] * r, cy + g_joy_sent[1] * r, FINGER_JOY);
        g_joy_down = 0;
    }
}

/* Keys other than movement (polled each frame) and the mode switch. 1 = handled. */
static int input_key(const SDL_KeyboardEvent *e)
{
    if (g_keymap_on <= 0 || e->repeat)
        return 0;
    int down = e->type == SDL_KEYDOWN, b = -1;
    switch (e->keysym.sym) {
    case SDLK_F1:
        if (down) {
            g_mouse_battle = !g_mouse_battle;
            glog("mouse: %s", g_mouse_battle ? "battle (LMB attack, RMB skill 1)" : "touch");
        }
        return 1;
    case SDLK_j: case SDLK_RETURN: b = BTN_ATTACK; break;
    case SDLK_1: b = BTN_SKILL1; break;
    case SDLK_2: b = BTN_SKILL2; break;
    case SDLK_3: b = BTN_SKILL3; break;
    case SDLK_4: b = BTN_SKILL4; break;
    case SDLK_SPACE: b = BTN_DODGE; break;
    default: return 0;
    }
    btn_press(b, down);
    return 1;
}

/* Mouse buttons in battle mode. 1 = handled (not passed on as a touch). */
static int input_mouse_button(const SDL_MouseButtonEvent *e)
{
    if (g_keymap_on <= 0 || !g_mouse_battle)
        return 0;
    int down = e->type == SDL_MOUSEBUTTONDOWN;
    if (e->button == SDL_BUTTON_LEFT)
        btn_press(BTN_ATTACK, down);
    else if (e->button == SDL_BUTTON_RIGHT)
        btn_press(BTN_SKILL1, down);
    else
        return 0;
    return 1;
}

/* For the window title. */
static const char *input_mode_name(void)
{
    if (g_keymap_on <= 0)
        return "keys off";
    return g_mouse_battle ? "mouse: battle (F1)" : "mouse: touch (F1)";
}
