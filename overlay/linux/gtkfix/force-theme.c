/*
 * LD_PRELOAD shim for Celtx 2.9.7: force a light GTK2 theme.
 *
 * GNOME pushes the desktop theme name through XSETTINGS, which overrides
 * GTK2_RC_FILES. If the desktop theme is dark (and ships a GTK2 variant),
 * Celtx inherits light text colours and the script editor becomes
 * unreadable (light text on its hard-coded white page).
 * Settings set with gtk_settings_set_string_property() have APPLICATION
 * priority, which beats XSETTINGS, so we set the theme right after gtk_init.
 *
 * Theme name can be changed with CELTX_GTK_THEME (default: Adwaita).
 * Built without GTK headers on purpose (no gtk2-devel needed).
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdlib.h>

typedef int gboolean;
typedef void GtkSettings;

typedef void GdkDisplay;
typedef void GdkScreen;

static void force_theme_on(GtkSettings *s)
{
    void (*set_string)(GtkSettings *, const char *, const char *, const char *) =
        (void (*)(GtkSettings *, const char *, const char *, const char *))
            dlsym(RTLD_DEFAULT, "gtk_settings_set_string_property");
    if (!s || !set_string)
        return;
    const char *theme = getenv("CELTX_GTK_THEME");
    set_string(s, "gtk-theme-name", theme && *theme ? theme : "Adwaita", "celtx-gtkfix");
}

/* Celtx (XULRunner 1.9) does not call gtk_init: it uses gtk_parse_args +
 * gdk_display_open, so hook the display opening and theme that screen. */
GdkDisplay *gdk_display_open(const char *name)
{
    GdkDisplay *(*real)(const char *) =
        (GdkDisplay *(*)(const char *))dlsym(RTLD_NEXT, "gdk_display_open");
    GdkDisplay *d = real(name);
    if (d) {
        GdkScreen *(*def_screen)(GdkDisplay *) =
            (GdkScreen *(*)(GdkDisplay *))dlsym(RTLD_DEFAULT, "gdk_display_get_default_screen");
        GtkSettings *(*for_screen)(GdkScreen *) =
            (GtkSettings *(*)(GdkScreen *))dlsym(RTLD_DEFAULT, "gtk_settings_get_for_screen");
        if (def_screen && for_screen)
            force_theme_on(for_screen(def_screen(d)));
    }
    return d;
}

static void force_theme(void)
{
    GtkSettings *(*get_default)(void) =
        (GtkSettings *(*)(void))dlsym(RTLD_DEFAULT, "gtk_settings_get_default");
    if (get_default)
        force_theme_on(get_default());
}

void gtk_init(int *argc, char ***argv)
{
    void (*real)(int *, char ***) =
        (void (*)(int *, char ***))dlsym(RTLD_NEXT, "gtk_init");
    real(argc, argv);
    force_theme();
}

gboolean gtk_init_check(int *argc, char ***argv)
{
    gboolean (*real)(int *, char ***) =
        (gboolean (*)(int *, char ***))dlsym(RTLD_NEXT, "gtk_init_check");
    gboolean ok = real(argc, argv);
    if (ok)
        force_theme();
    return ok;
}
