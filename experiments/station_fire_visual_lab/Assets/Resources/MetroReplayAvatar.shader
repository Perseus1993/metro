Shader "MetroReplay/Avatar"
{
    Properties
    {
        _Color ("Color", Color) = (1,1,1,1)
        _MainTex ("Base Color", 2D) = "white" {}
        [HideInInspector] _UsePlanarUV ("Use Planar UV", Float) = 0
        [HideInInspector] _PlanarUVTransform ("Planar UV Transform", Vector) = (0.5,0.54645,0.5,0)
        [HideInInspector] _SkinAtlasRect ("Skin Atlas Rect", Vector) = (1,1,0,0)
    }
    SubShader
    {
        Tags { "RenderType"="Opaque" "Queue"="Geometry" }
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"

            struct appdata
            {
                float4 vertex : POSITION;
                float3 normal : NORMAL;
                float2 uv : TEXCOORD0;
            };

            struct v2f
            {
                float4 vertex : SV_POSITION;
                float3 normal : TEXCOORD0;
                float2 uv : TEXCOORD1;
            };

            fixed4 _Color;
            sampler2D _MainTex;
            float4 _MainTex_ST;
            float _UsePlanarUV;
            float4 _PlanarUVTransform;
            float4 _SkinAtlasRect;

            v2f vert(appdata input)
            {
                v2f output;
                output.vertex = UnityObjectToClipPos(input.vertex);
                output.normal = UnityObjectToWorldNormal(input.normal);
                float2 authoredUv = TRANSFORM_TEX(input.uv, _MainTex);
                float2 planarUv = input.vertex.xy * _PlanarUVTransform.xy
                    + _PlanarUVTransform.zw;
                planarUv = saturate(planarUv);
                planarUv = planarUv * _SkinAtlasRect.xy + _SkinAtlasRect.zw;
                output.uv = lerp(authoredUv, planarUv, saturate(_UsePlanarUV));
                return output;
            }

            fixed4 frag(v2f input) : SV_Target
            {
                float3 lightDirection = normalize(_WorldSpaceLightPos0.xyz);
                float diffuse = saturate(dot(normalize(input.normal), lightDirection));
                float lighting = 0.64 + diffuse * 0.52;
                fixed4 textureColor = tex2D(_MainTex, input.uv);
                return fixed4(_Color.rgb * textureColor.rgb * lighting, _Color.a * textureColor.a);
            }
            ENDCG
        }
    }
}
