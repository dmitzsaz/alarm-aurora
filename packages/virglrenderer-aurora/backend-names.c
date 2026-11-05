/* SPDX-License-Identifier: MIT */
/* Exercise the real dispatcher, including its open path during context creation. */
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#include "drm_hw.h"

/* Stand in for libdrm and the renderer dependencies, not the dispatcher. */
#define ENABLE_DRM_ASAHI 1
#define DRM_RENDERER_H_
#define DRM_UTIL_H_
#define ASAHI_RENDERER_H_
#define DRM_NODE_RENDER 2
#define DRM_IOCTL_SET_CLIENT_NAME 0
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define drm_log(...) ((void)0)

struct virgl_context { int unused; };
struct drm_set_client_name { uint64_t name_len, name; };
typedef struct {
   int version_major, version_minor, version_patchlevel;
   const char *name;
} drmVersion, *drmVersionPtr;

static const char *host_name;
static int opens, closes, probes, creates, client_names;
static int version_failure, probe_failure;
static drmVersion version;
static struct virgl_context context;

static int
drmOpenWithType(const char *name, const char *bus, int type)
{
   assert(!bus && type == DRM_NODE_RENDER);
   ++opens;
   return strcmp(name, host_name) ? -1 : 17;
}

static drmVersionPtr
drmGetVersion(int fd)
{
   assert(fd == 17 || fd == 31);
   version.name = host_name;
   version.version_major = !strcmp(host_name, "aurora") ? 1 : 0;
   version.version_minor = 0;
   version.version_patchlevel = 0;
   return version_failure ? NULL : &version;
}

static void drmFreeVersion(drmVersionPtr v) { assert(v == &version); }
static int test_close(int fd) { assert(fd == 17 || fd == 31); ++closes; return 0; }
static int
drmIoctl(int fd, unsigned long request, void *data)
{
   struct drm_set_client_name *n = data;
   assert((fd == 17 || fd == 31) && request == DRM_IOCTL_SET_CLIENT_NAME);
   assert(n->name_len == 4 && !memcmp((void *)(uintptr_t)n->name, "test", 4));
   ++client_names;
   return 0;
}

static int
asahi_renderer_probe(int fd, struct virgl_renderer_capset_drm *c)
{
   assert((fd == 17 || fd == 31) && c->context_type == VIRTGPU_DRM_CONTEXT_ASAHI);
   ++probes;
   return probe_failure;
}

static struct virgl_context *
asahi_renderer_create(int fd, size_t len, const char *name)
{
   assert((fd == 17 || fd == 31) && len == 4 && !strcmp(name, "test"));
   ++creates;
   return &context;
}

#define close test_close
#include "drm/drm_renderer.c"
#undef close

static void
reset(const char *name)
{
   host_name = name;
   opens = closes = probes = creates = client_names = 0;
   version_failure = probe_failure = 0;
   memset(&capset, 0, sizeof(capset));
}

static void
check_name(const char *name, int supplied_fd)
{
   reset(name);
   int expected_opens = supplied_fd >= 0 ? 0 : (!strcmp(name, "aurora") ? 2 : 1);
   assert(drm_renderer_init(supplied_fd) == 0);
   assert(opens == expected_opens && closes == 1 && probes == 1);
   struct virgl_renderer_capset_drm c;
   assert(drm_renderer_capset(&c) == sizeof(c));
   assert(c.context_type == VIRTGPU_DRM_CONTEXT_ASAHI);
   assert(c.version_major == (!strcmp(name, "aurora") ? 1u : 0u));
   assert(c.version_minor == 0 && c.version_patchlevel == 0);
   assert(drm_renderer_create(4, "test", supplied_fd) == &context);
   assert(opens == 2 * expected_opens && creates == 1 && client_names == 1);
   if (supplied_fd < 0) {
      host_name = "unrelated";
      assert(drm_renderer_create(4, "test", -1) == NULL);
      assert(creates == 1);
   }
}

int
main(void)
{
   check_name("asahi", -1);
   check_name("aurora", -1);
   check_name("asahi", 31);
   check_name("aurora", 31);

   reset("unrelated");
   assert(drm_renderer_init(31) == -ENODEV);
   assert(opens == 0 && closes == 1 && probes == 0);
   reset("unrelated");
   assert(drm_renderer_init(-1) == -ENODEV);
   assert(opens == 2 && closes == 0 && probes == 0);
   reset("aurora");
   version_failure = 1;
   assert(drm_renderer_init(-1) == -ENOMEM && closes == 1);
   reset("aurora");
   probe_failure = -EINVAL;
   assert(drm_renderer_init(-1) == -EINVAL && closes == 1);
   assert(capset.context_type == 0);
   assert(drm_renderer_create(4, "test", -1) == NULL);
   assert(creates == 0);
   puts("asahi/aurora dispatch: probing, supplied fd, reopen, rejection and error paths PASS");
   return 0;
}
