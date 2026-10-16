/*
 * ew3gl module 8/12: object names, shaders and programs, buffers, textures.
 *
 * Payload layouts are the guest's (port/src/gl_bridge.cpp); a data length of
 * -1 stands for a NULL pointer (glBufferData / glTexImage* with no contents).
 */

/* Bound buffers as the guest names them: draws with client arrays rebind these afterwards (module 5). */
static int32_t g_cur_array, g_cur_elem;

/* True on a GLES 3.0 context: the ES3-only entry points may be called. */
static int es3(void)
{
    static int v = -1;
    if (v < 0) {
        const char *s = (const char *)glGetString(GL_VERSION);
        v = s && strstr(s, "OpenGL ES 3") ? 1 : 0;
    }
    return v;
}

static void op_gen(void)
{
    int32_t kind = rd_i(), n = rd_i();
    if (n <= 0 || n > 65536)
        return;
    GLuint stack[64];
    GLuint *host = n <= 64 ? stack : (GLuint *)malloc((size_t)n * sizeof(GLuint));
    if (!host)
        return;
    struct idmap *m = NULL;
    switch (kind) {
    case GEN_TEX: glGenTextures(n, host); m = &g_ids.tex; break;
    case GEN_BUF: glGenBuffers(n, host); m = &g_ids.buf; break;
    case GEN_FBO: glGenFramebuffers(n, host); m = &g_ids.fbo; break;
    case GEN_RBO: glGenRenderbuffers(n, host); m = &g_ids.rbo; break;
    default: GLOG_LIMITED(g_exec_errors, 20, "GEN: unknown kind %d", kind); break;
    }
    for (int32_t k = 0; m && k < n; k++)
        idmap_put(m, rd_i(), host[k]);
    if (host != stack)
        free(host);
}

static void op_delete(void)
{
    int32_t kind = rd_i(), n = rd_i();
    for (int32_t k = 0; k < n && !g_underrun; k++) {
        int32_t g = rd_i();
        GLuint h;
        switch (kind) {
        case GEN_TEX: h = idmap_get(&g_ids.tex, g); glDeleteTextures(1, &h); idmap_put(&g_ids.tex, g, 0); break;
        case GEN_BUF: h = idmap_get(&g_ids.buf, g); glDeleteBuffers(1, &h); idmap_put(&g_ids.buf, g, 0); break;
        case GEN_FBO: h = idmap_get(&g_ids.fbo, g); glDeleteFramebuffers(1, &h); idmap_put(&g_ids.fbo, g, 0); break;
        case GEN_RBO: h = idmap_get(&g_ids.rbo, g); glDeleteRenderbuffers(1, &h); idmap_put(&g_ids.rbo, g, 0); break;
        default: break;
        }
        if (kind == GEN_BUF) {
            if (g == g_cur_array) g_cur_array = 0;
            if (g == g_cur_elem) g_cur_elem = 0;
        }
    }
}

static void op_create_shader(void)
{
    GLenum type = (GLenum)rd_i();
    int32_t id = rd_i();
    idmap_put(&g_ids.shader, id, glCreateShader(type));
}

static void op_create_program(void)
{
    idmap_put(&g_ids.prog, rd_i(), glCreateProgram());
}

static void op_shader_source(void)
{
    GLuint sh = idmap_get(&g_ids.shader, rd_i());
    int32_t n = rd_i();
    const GLchar *src = (const GLchar *)rd_data(n);
    if (!src)
        return;
    GLint len = n;
    glShaderSource(sh, 1, &src, &len);
}

/* ------------------------------------------------------------- buffers */

static void op_bind_buffer(void)
{
    GLenum target = (GLenum)rd_i();
    int32_t id = rd_i();
    if (target == GL_ARRAY_BUFFER)
        g_cur_array = id;
    else if (target == GL_ELEMENT_ARRAY_BUFFER)
        g_cur_elem = id;
    glBindBuffer(target, idmap_get(&g_ids.buf, id));
}

static void op_buffer_data(void)
{
    GLenum target = (GLenum)rd_i();
    int32_t size = rd_i();
    GLenum usage = (GLenum)rd_i();
    int32_t n = rd_i();
    glBufferData(target, size, rd_data(n), usage);
}

static void op_buffer_sub_data(void)
{
    GLenum target = (GLenum)rd_i();
    int32_t offset = rd_i(), size = rd_i(), n = rd_i();
    const void *d = rd_data(n);
    if (d)
        glBufferSubData(target, offset, size, d);
}

/* ------------------------------------------------------------- textures */

/* The guest has already applied its GL_UNPACK_ALIGNMENT when it measured the data, and the
 * glPixelStorei call itself was forwarded, so the host unpacks exactly what was sent. */

static void op_tex_image_2d(void)
{
    int32_t t = rd_i(), lv = rd_i(), ifmt = rd_i(), w = rd_i(), h = rd_i(), bd = rd_i(), f = rd_i(), ty = rd_i();
    int32_t n = rd_i();
    glTexImage2D((GLenum)t, lv, ifmt, w, h, bd, (GLenum)f, (GLenum)ty, rd_data(n));
}

static void op_tex_sub_image_2d(void)
{
    int32_t t = rd_i(), lv = rd_i(), x = rd_i(), y = rd_i(), w = rd_i(), h = rd_i(), f = rd_i(), ty = rd_i();
    int32_t n = rd_i();
    const void *d = rd_data(n);
    if (d)
        glTexSubImage2D((GLenum)t, lv, x, y, w, h, (GLenum)f, (GLenum)ty, d);
}

static void op_compressed_tex_image_2d(void)
{
    int32_t t = rd_i(), lv = rd_i(), ifmt = rd_i(), w = rd_i(), h = rd_i(), bd = rd_i(), size = rd_i();
    int32_t n = rd_i();
    glCompressedTexImage2D((GLenum)t, lv, (GLenum)ifmt, w, h, bd, size, rd_data(n));
}

static void op_compressed_tex_sub_image_2d(void)
{
    int32_t t = rd_i(), lv = rd_i(), x = rd_i(), y = rd_i(), w = rd_i(), h = rd_i(), f = rd_i(), size = rd_i();
    int32_t n = rd_i();
    const void *d = rd_data(n);
    if (d)
        glCompressedTexSubImage2D((GLenum)t, lv, x, y, w, h, (GLenum)f, size, d);
}

static void op_tex_image_3d(void)
{
    int32_t t = rd_i(), lv = rd_i(), ifmt = rd_i(), w = rd_i(), h = rd_i(), dp = rd_i(), bd = rd_i();
    int32_t f = rd_i(), ty = rd_i(), n = rd_i();
    const void *d = rd_data(n);
    if (!es3()) {
        GLOG_LIMITED(g_exec_errors, 20, "glTexImage3D needs a GLES 3.0 context; dropped");
        return;
    }
    glTexImage3D((GLenum)t, lv, ifmt, w, h, dp, bd, (GLenum)f, (GLenum)ty, d);
}

static void op_tex_sub_image_3d(void)
{
    int32_t t = rd_i(), lv = rd_i(), x = rd_i(), y = rd_i(), z = rd_i(), w = rd_i(), h = rd_i(), dp = rd_i();
    int32_t f = rd_i(), ty = rd_i(), n = rd_i();
    const void *d = rd_data(n);
    if (d && es3())
        glTexSubImage3D((GLenum)t, lv, x, y, z, w, h, dp, (GLenum)f, (GLenum)ty, d);
}

static void op_compressed_tex_image_3d(void)
{
    int32_t t = rd_i(), lv = rd_i(), ifmt = rd_i(), w = rd_i(), h = rd_i(), dp = rd_i(), bd = rd_i();
    int32_t size = rd_i(), n = rd_i();
    const void *d = rd_data(n);
    if (es3())
        glCompressedTexImage3D((GLenum)t, lv, (GLenum)ifmt, w, h, dp, bd, size, d);
}

static void op_compressed_tex_sub_image_3d(void)
{
    int32_t t = rd_i(), lv = rd_i(), x = rd_i(), y = rd_i(), z = rd_i(), w = rd_i(), h = rd_i(), dp = rd_i();
    int32_t f = rd_i(), size = rd_i(), n = rd_i();
    const void *d = rd_data(n);
    if (d && es3())
        glCompressedTexSubImage3D((GLenum)t, lv, x, y, z, w, h, dp, (GLenum)f, size, d);
}
