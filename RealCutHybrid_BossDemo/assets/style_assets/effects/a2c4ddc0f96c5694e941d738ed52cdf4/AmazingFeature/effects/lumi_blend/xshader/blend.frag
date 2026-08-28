precision highp float;
varying highp vec2 uv0;
uniform sampler2D u_SourceTexture;
uniform sampler2D u_BaseTexure;
uniform int u_BlendMode;
uniform int u_NeedBlend;
uniform int u_layerType;

#define LAYER_TYPE_ADJUSTMENT 1
#define BLEND_MODE_NORMAL 0

float random(vec2 st)
{
    return fract(sin(dot(st.xy, vec2(12.9898, 78.233))) * 43758.5453123);
}

#define BlendOverlayf(s, d)      (d < 0.5 ? (2.0 * d * s) : (1.0 - 2.0 * (1.0 - d) * (1.0 - s))) 
#define BlendOverlay(s, d)       vec3(BlendOverlayf(s.r, d.r), BlendOverlayf(s.g, d.g), BlendOverlayf(s.b, d.b))
#define BlendScreen(s, d)        (s + d - s * d)
#define BlendMultiply(s, d)      (s * d)
#define BlendDifference(s, d)    (abs(s - d))
#define BlendAdd(s, d)           (s + d)
#define BlendSubtract(s, d)      max(vec3(0.0), (d - s))
#define BlendDarken(s, d)        min(s, d)
#define BlendLighten(s, d)       max(s, d)
#define BlendExclusion(s, d)     (d + s - 2.0 * d * s)

float softLightf(float s, float d)
{
    return (s < 0.5) ? d - (1.0 - 2.0 * s) * d * (1.0 - d) : (d < 0.25) ? d + (2.0 * s - 1.0) * d * ((16.0 * d - 12.0) * d + 3.0) : d + (2.0 * s - 1.0) * (sqrt(d) - d);
}
vec3 BlendSoftLight(vec3 s, vec3 d)
{
    return vec3(softLightf(s.r, d.r), softLightf(s.g, d.g), softLightf(s.b, d.b));
}

float hardLightf(float s, float d)
{
    return (s < 0.5) ? 2.0 * s * d : 1.0 - 2.0 * (1.0 - s) * (1.0 - d);
}
vec3 BlendHardLight(vec3 s, vec3 d)
{
    return vec3(hardLightf(s.r, d.r), hardLightf(s.g, d.g), hardLightf(s.b, d.b));
}

float getLuminosity(vec3 color)
{
    return dot(color, vec3(0.299, 0.587, 0.114));
}

vec3 setLuminosity(vec3 c, float lum)
{
    float d = lum - getLuminosity(c);
    c.rgb += vec3(d);

    // clip back into legal range
    lum = getLuminosity(c);
    float cMin = min(c.r, min(c.g, c.b));
    float cMax = max(c.r, max(c.g, c.b));

    if (cMin < 0.0)
        c = mix(vec3(lum, lum, lum), c, lum / (lum - cMin));

    if (cMax > 1.0)
        c = mix(vec3(lum, lum, lum), c, (1. - lum) / (cMax - lum));

    return c;
}

vec3 setSaturationMinMidMax(vec3 cSorted, float s)
{
    if (cSorted.z > cSorted.x)
    {
        cSorted.y = (((cSorted.y - cSorted.x) * s) / (cSorted.z - cSorted.x));
        cSorted.z = s;
    }
    else
    {
        cSorted.y = 0.0;
        cSorted.z = 0.0;
    }

    cSorted.x = 0.0;

    return cSorted;
}

float getSaturation(vec3 c)
{
    return max(c.r, max(c.g, c.b)) - min(c.r, min(c.g, c.b));
}

vec3 setSaturation(vec3 c, float s)
{
    if (c.r <= c.g && c.r <= c.b)
    {
        if (c.g <= c.b)
            c.rgb = setSaturationMinMidMax(c.rgb, s);
        else
            c.rbg = setSaturationMinMidMax(c.rbg, s);
    }
    else if (c.g <= c.r && c.g <= c.b)
    {
        if (c.r <= c.b)
            c.grb = setSaturationMinMidMax(c.grb, s);
        else
            c.gbr = setSaturationMinMidMax(c.gbr, s);
    }
    else
    {
        if (c.r <= c.g)
            c.brg = setSaturationMinMidMax(c.brg, s);
        else
            c.bgr = setSaturationMinMidMax(c.bgr, s);
    }

    return c;
}

vec3 BlendHue(vec3 s, vec3 d)
{
    return setLuminosity(setSaturation(s, getSaturation(d)), getLuminosity(d));
}

vec3 BlendSaturation(vec3 s, vec3 d)
{
    return setLuminosity(setSaturation(d, getSaturation(s)), getLuminosity(d));
}

vec3 BlendColor(vec3 s, vec3 d)
{
    return setLuminosity(s, getLuminosity(d));
}

vec3 BlendDarkerColor(vec3 s, vec3 d)
{
    return getLuminosity(d) <= getLuminosity(s) ? d : s;
}

vec3 BlendLighterColor(vec3 s, vec3 d)
{
    return getLuminosity(d) > getLuminosity(s) ? d : s;
}

vec3 BlendLuminosity(vec3 s, vec3 d)
{
    return setLuminosity(d, getLuminosity(s));
}

float colorBurn(float s, float d)
{
    if (d >= 1.0)
        return 1.0;
    else if (s <= 0.0)
        return 0.0;
    else
        return 1.0 - min(1.0, (1.0 - d) / s);
}
vec3 BlendColorBurn(vec3 s, vec3 d)
{
    return vec3(colorBurn(s.r, d.r), colorBurn(s.g, d.g), colorBurn(s.b, d.b));
}

float linearBurn(float s, float d)
{
    return max(0.0, d + s - 1.0);
}
vec3 BlendLinearBurn(vec3 s, vec3 d)
{
    return vec3(linearBurn(s.r, d.r), linearBurn(s.g, d.g), linearBurn(s.b, d.b));
}

float colorDodge(float s, float d)
{
    if (d <= 0.0)
        return 0.0;
    if (s >= 1.0)
        return 1.0;
    else
        return min(1.0, d / (1.0 - s));
}
vec3 BlendColorDodge(vec3 s, vec3 d)
{
    return vec3(colorDodge(s.r, d.r), colorDodge(s.g, d.g), colorDodge(s.b, d.b));
}

float linearDodge(float s, float d)
{
    return min(1.0, d + s);
}
vec3 BlendLinearDodge(vec3 s, vec3 d)
{
    return vec3(linearDodge(s.r, d.r), linearDodge(s.g, d.g), linearDodge(s.b, d.b));
}

float vividLight(float s, float d)
{
    return (s <= 0.5) ? colorBurn(d, 2.0 * s) : colorDodge(d, 2.0 * (s - 0.5));
}
vec3 BlendVividLight(vec3 s, vec3 d)
{
    return vec3(vividLight(s.r, d.r), vividLight(s.g, d.g), vividLight(s.b, d.b));
}

float linearLight(float s, float d)
{
    return (s <= 0.5) ? linearBurn(d, 2.0 * s) : linearDodge(d, 2.0 * (s - 0.5));
}
vec3 BlendLinearLight(vec3 s, vec3 d)
{
    return vec3(linearLight(s.r, d.r), linearLight(s.g, d.g), linearLight(s.b, d.b));
}

float pinLight(float s, float d)
{
    return (s <= 0.5) ? min(d, 2.0 * s) : max(d, 2.0 * (s - 0.5));
}
vec3 BlendPinLight(vec3 s, vec3 d)
{
    return vec3(pinLight(s.r, d.r), pinLight(s.g, d.g), pinLight(s.b, d.b));
}

float hardMix(float s, float d)
{
    return (d + s >= 1.0) ? 1.0 : 0.0;
}
vec3 BlendHardMix(vec3 s, vec3 d)
{
    return vec3(hardMix(s.r, d.r), hardMix(s.g, d.g), hardMix(s.b, d.b));
}

float divide(float s, float d)
{
    return s > 0.0 ? min(1.0, d / s) : 1.0;
}
vec3 BlendDivide(vec3 s, vec3 d)
{
    return vec3(divide(s.r, d.r), divide(s.g, d.g), divide(s.b, d.b));
}

void main()
{
    vec4 baseColor = texture2D(u_BaseTexure, uv0);
    if (u_NeedBlend == 0)
    {
        gl_FragColor = baseColor;
        return;
    }

    if (u_layerType == LAYER_TYPE_ADJUSTMENT && u_BlendMode == BLEND_MODE_NORMAL)
    {
        gl_FragColor = texture2D(u_SourceTexture, uv0);
        return;
    }

    vec4 srcColor = texture2D(u_SourceTexture, uv0);
    srcColor.rgb /= (srcColor.a + 0.0001);
    baseColor.rgb /= (baseColor.a + 0.0001);

    vec4 blendColor = baseColor;
    if (u_BlendMode == 1)
    {
        blendColor.rgb = BlendAdd(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 2)
    {
        blendColor.rgb = BlendMultiply(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 3)
    {
        blendColor.rgb = BlendDifference(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 4)
    {
        blendColor.rgb = BlendOverlay(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 5)
    {
        blendColor.rgb = BlendDarken(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 6)
    {
        blendColor.rgb = BlendLighten(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 7)
    {
        blendColor.rgb = BlendSoftLight(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 8)
    {
        blendColor.rgb = BlendHardLight(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 9)
    {
        blendColor.rgb = BlendHue(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 10)
    {
        blendColor.rgb = BlendSaturation(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 11)
    {
        blendColor.rgb = BlendColor(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 12)
    {
        blendColor.rgb = BlendScreen(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 13)
    {
        blendColor.rgb = BlendColorBurn(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 14)
    {
        blendColor.rgb = BlendLinearBurn(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 15)
    {
        blendColor.rgb = BlendColorDodge(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 16)
    {
        blendColor.rgb = BlendLinearDodge(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 17)
    {
        blendColor.rgb = BlendVividLight(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 18)
    {
        blendColor.rgb = BlendLinearLight(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 19)
    {
        blendColor.rgb = BlendPinLight(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 20)
    {
        blendColor.rgb = BlendHardMix(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 21)
    {
        blendColor.rgb = BlendExclusion(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 22)
    {
        blendColor.rgb = BlendSubtract(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 23)
    {
        blendColor.rgb = BlendDivide(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 24)
    {
        blendColor.rgb = BlendLuminosity(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 25)
    {
        blendColor.rgb = BlendLighterColor(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 26)
    {
        blendColor.rgb = BlendDarkerColor(srcColor.rgb, baseColor.rgb);
    }
    else if (u_BlendMode == 27) // Dissolve
    {
        if (srcColor.a == 1.0 || (srcColor.a > 0.0 && srcColor.a > random(uv0)))
        {
            blendColor.rgb = srcColor.rgb;
        }
    }
    else // normal
    {
        blendColor.rgb = srcColor.rgb;
    }

    vec4 result = vec4(0.);
    // The following code is to perform "alpha compositing". Please NOTICE that: 
    // the input "srcColor" and "baseColor" have straight alpha, while the "result" 
    // has premultiplied alpha (because result.rgb does NOT divided by result.a)..
    result.rgb = baseColor.rgb * baseColor.a * (1.0 - srcColor.a) +
        srcColor.rgb * srcColor.a * (1.0 - baseColor.a) +
        srcColor.a * baseColor.a * blendColor.rgb;
    result.a = srcColor.a + baseColor.a * (1.0 - srcColor.a);
    gl_FragColor = result;
}
