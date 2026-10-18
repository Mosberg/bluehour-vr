"""GLSL sources: video quad, eye renderer (projections, stereo, lens distortion), present pass.
"""

# --------------------------------------------------------------------------------------
# Shaders
# --------------------------------------------------------------------------------------

VERT = """
#version 330 core
out vec2 vUv;
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    vUv = p;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
"""

EYE_FRAG = """
#version 330 core
in vec2 vUv;
out vec4 frag;
uniform sampler2D uVideo;
uniform mat3  uRot;        // view -> world (head orientation)
uniform float uEye;        // -1 left, +1 right
uniform int   uProj;       // 0 flat, 1 curved, 2 vr180, 3 vr360
uniform int   uStereo;     // 0 mono, 1 side-by-side, 2 over-under
uniform int   uSwap;
uniform float uAspect;     // per-eye image aspect ratio
uniform float uScreenW;    // virtual screen width
uniform float uDist;       // virtual screen distance
uniform float uTanHalf;    // field-of-view scale
uniform float uVpAspect;   // eye viewport aspect
uniform float uIpd;
uniform float uCA;
uniform vec3  uPos;        // head position (metres, world space) - used by flat / curved screens
uniform vec4  uK;          // radial distortion coefficients
const float PI = 3.14159265359;
const vec3 BG = vec3(0.012);

vec3 scene(vec2 w) {
    vec3 d  = normalize(vec3(w * uTanHalf, -1.0));
    vec3 wd = uRot * d;
    vec3 wo = uRot * vec3(uEye * uIpd * 0.5, 0.0, 0.0) + uPos;
    float h = uScreenW / uAspect;
    vec2 uv;
    if (uProj == 0) {
        if (wd.z > -1e-4) return BG;
        float t = (-uDist - wo.z) / wd.z;
        vec3 p = wo + t * wd;
        uv = vec2(p.x / uScreenW + 0.5, p.y / h + 0.5);
    } else if (uProj == 1) {
        float a = wd.x * wd.x + wd.z * wd.z;
        if (a < 1e-6) return BG;
        float b = 2.0 * (wo.x * wd.x + wo.z * wd.z);
        float c = wo.x * wo.x + wo.z * wo.z - uDist * uDist;
        float disc = b * b - 4.0 * a * c;
        if (disc < 0.0) return BG;
        float t = (-b + sqrt(disc)) / (2.0 * a);
        vec3 p = wo + t * wd;
        float phi = atan(p.x, -p.z);
        uv = vec2(phi / (uScreenW / uDist) + 0.5, p.y / h + 0.5);
    } else {
        float lon = atan(wd.x, -wd.z);
        float lat = asin(clamp(wd.y, -1.0, 1.0));
        if (uProj == 2) {
            if (abs(lon) > PI * 0.5) return BG;
            uv = vec2(lon / PI + 0.5, lat / PI + 0.5);
        } else {
            uv = vec2(lon / (2.0 * PI) + 0.5, lat / PI + 0.5);
        }
    }
    if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) return BG;
    float e = (uEye > 0.0) ? 1.0 : 0.0;
    if (uSwap == 1) e = 1.0 - e;
    if (uStereo == 1) uv.x = uv.x * 0.5 + 0.5 * e;
    else if (uStereo == 2) uv.y = uv.y * 0.5 + 0.5 * (1.0 - e);
    return texture(uVideo, uv).rgb;
}

void main() {
    vec2 ndc = vUv * 2.0 - 1.0;
    vec2 p = ndc * vec2(uVpAspect, 1.0);
    float rr = dot(p, p);
    float sc = uK.x + rr * (uK.y + rr * (uK.z + rr * uK.w));
    vec2 w = p * sc;
    vec3 col;
    col.r = scene(w * (1.0 - uCA)).r;
    col.g = scene(w).g;
    col.b = scene(w * (1.0 + uCA)).b;
    frag = vec4(col, 1.0);
}
"""

PRESENT_FRAG = """
#version 330 core
in vec2 vUv;
out vec4 frag;
uniform sampler2D uTex;
uniform int uRotate;
void main() {
    vec2 uv = vUv;
    if (uRotate == 1) uv = vec2(vUv.y, 1.0 - vUv.x);
    else if (uRotate == 2) uv = vec2(1.0) - vUv;
    else if (uRotate == 3) uv = vec2(1.0 - vUv.y, vUv.x);
    frag = vec4(texture(uTex, uv).rgb, 1.0);
}
"""
