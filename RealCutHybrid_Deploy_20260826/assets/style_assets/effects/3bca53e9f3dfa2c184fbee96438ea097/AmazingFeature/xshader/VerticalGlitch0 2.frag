precision mediump float;
varying vec2 texCoord;

uniform float progress;
uniform sampler2D inputImageTexture;

void main() {
    vec4 blackColor = vec4(0.0, 0.0, 0.0, 1.0);
    gl_FragColor = mix(texture2D(inputImageTexture, texCoord), blackColor, 1.0-progress);
}