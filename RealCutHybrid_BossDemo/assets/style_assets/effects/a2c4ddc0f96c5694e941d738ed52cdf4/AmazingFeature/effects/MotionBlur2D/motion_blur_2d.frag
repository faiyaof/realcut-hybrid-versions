precision highp float;
varying highp vec2 uv0;

uniform sampler2D u_inputImageTexture;
uniform vec4 u_ScreenParams;
uniform float u_minSamples;
uniform float u_maxSamples;
uniform float u_mirrorEdge;
uniform float u_dither;
uniform vec2 u_pivotVec2Vector[6];
uniform vec2 u_positionVec2Vector[6];
uniform vec2 u_scaleVec2Vector[6];
uniform float u_rotationFloatVector[6];

#define kSamplesPerFrame 256.0
#define PI 3.1415926
vec2 Affine(vec2 uv, float theta, vec2 offset, vec2 anchor, vec2 scale)
{
    // offset
    uv -= offset;
    // rotate
    uv -= 0.5;
    uv.y *= u_ScreenParams.y / u_ScreenParams.x;
    float sint = sin(theta);
    float cost = cos(theta);
    mat2 rot = mat2(
        cost, sint,
        -sint, cost
    );
    uv = rot * uv;
    uv.y *= u_ScreenParams.x / u_ScreenParams.y;
    // scale
    uv = uv * (1. / scale);
    uv += 0.5;
    uv += anchor;
    return uv;
}

vec2 Mirror(vec2 x) { return abs(mod(x-1., 2.)-1.); }

float uvProtect(vec2 uvTemp)
{
    return step(0.,uvTemp.x)*step(0.,uvTemp.y)*step(uvTemp.x,1.0)*step(uvTemp.y,1.0);
}

vec2 interUV(float w, vec2 uv_0, vec2 uv_1, vec2 uv_2, vec2 uv_3, vec2 uv_4, vec2 uv_5)
{
    return mix(uv_0, uv_1, w*5.0) * step(w, 0.2) +
            mix(uv_1, uv_2, w*5.0-1.0) * (1.0-step(w, 0.2)) * step(w, 0.4) +
            mix(uv_2, uv_3, w*5.0-2.0) * (1.0-step(w, 0.4)) * step(w, 0.6) +
            mix(uv_3, uv_4, w*5.0-3.0) * (1.0-step(w, 0.6)) * step(w, 0.8) +
            mix(uv_4, uv_5, w*5.0-4.0) * (1.0-step(w, 0.8));
}

float hash21(float p, float seed)
{
    vec2 p2 = fract(vec2(p, seed) * 13.517);
    p2 += dot(p2, p2.yx + 22.541);
    return fract((p2.x + p2.y) * p2.y);
}

void main() {
    vec2 uv_0 = Affine(uv0, u_rotationFloatVector[0] * PI / 180.0, u_positionVec2Vector[0], u_pivotVec2Vector[0], u_scaleVec2Vector[0]);
    vec2 uv_1 = Affine(uv0, u_rotationFloatVector[1] * PI / 180.0, u_positionVec2Vector[1], u_pivotVec2Vector[1], u_scaleVec2Vector[1]);
    vec2 uv_2 = Affine(uv0, u_rotationFloatVector[2] * PI / 180.0, u_positionVec2Vector[2], u_pivotVec2Vector[2], u_scaleVec2Vector[2]);
    vec2 uv_3 = Affine(uv0, u_rotationFloatVector[3] * PI / 180.0, u_positionVec2Vector[3], u_pivotVec2Vector[3], u_scaleVec2Vector[3]);
    vec2 uv_4 = Affine(uv0, u_rotationFloatVector[4] * PI / 180.0, u_positionVec2Vector[4], u_pivotVec2Vector[4], u_scaleVec2Vector[4]);
    vec2 uv_5 = Affine(uv0, u_rotationFloatVector[5] * PI / 180.0, u_positionVec2Vector[5], u_pivotVec2Vector[5], u_scaleVec2Vector[5]);

    float mins = max(u_minSamples, 2.0);
    float maxs = max(u_maxSamples, mins);
    float samples = floor(mins + (maxs - mins)*smoothstep(0.0, 0.2, length(uv_5-uv_0)));
    // float samples = max(maxSamples, 2.0);

    vec4 result = vec4(0.0);
    for (float i = 0.0; i <= kSamplesPerFrame; i+=1.0)
    {
        if (i >= samples) break;
        float w = i / (samples - 1.0);
        w += u_dither*(hash21(i+uv0.x, i*uv0.y)-0.5) / samples;
        vec2 uv = interUV(w, uv_0, uv_1, uv_2, uv_3, uv_4, uv_5);
        uv = step(u_mirrorEdge, 0.5)*uv + (1.0-step(u_mirrorEdge, 0.5))*Mirror(uv);
        result += texture2D(u_inputImageTexture, uv) * uvProtect(uv);
    }
    result /= samples;

    gl_FragColor = result;
}