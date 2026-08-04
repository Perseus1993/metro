Shader "Hidden/MetroReplay/Cinematic"
{
    Properties
    {
        _MainTex ("Texture", 2D) = "white" {}
    }
    SubShader
    {
        Cull Off ZWrite Off ZTest Always
        Pass
        {
            CGPROGRAM
            #pragma vertex vert_img
            #pragma fragment frag
            #include "UnityCG.cginc"

            sampler2D _MainTex;

            float3 Tonemap(float3 color)
            {
                color *= 1.05;
                return saturate((color * (2.51 * color + 0.03)) / (color * (2.43 * color + 0.59) + 0.14));
            }

            fixed4 frag(v2f_img input) : SV_Target
            {
                float4 source = tex2D(_MainTex, input.uv);
                float luminance = dot(source.rgb, float3(0.2126, 0.7152, 0.0722));
                float3 graded = lerp(luminance.xxx, source.rgb, 0.96);
                graded = (graded - 0.5) * 1.02 + 0.5;
                graded *= float3(1.01, 1.005, 0.995);
                graded = Tonemap(graded + 0.030);

                float2 centered = input.uv * 2.0 - 1.0;
                centered.x *= _ScreenParams.x / _ScreenParams.y;
                float vignette = smoothstep(1.45, 0.35, dot(centered, centered));
                graded *= lerp(0.92, 1.0, vignette);
                return float4(graded, source.a);
            }
            ENDCG
        }
    }
}
