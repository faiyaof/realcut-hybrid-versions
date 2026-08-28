precision highp float;
varying highp vec2 uv0;
uniform sampler2D inputTex;
uniform float alpha;
uniform float mirrorEdge;


float uvProtect(vec2 uv)
{
    vec2 uvp = step(vec2(0.0), uv) * step(uv, vec2(1.0));
    return uvp.x * uvp.y;
}
vec2 Mirror(vec2 x) { return abs(mod(x-1., 2.)-1.); }

void main()
{
    vec2 uv = step(mirrorEdge, 0.5)*uv0 + (1.0-step(mirrorEdge, 0.5))*Mirror(uv0);
    vec4 res = texture2D(inputTex, uv) * alpha * uvProtect(uv);
    // vec4 res = texture2D(inputTex,Mirror(uv0)) * alpha;
    gl_FragColor = res;
}
