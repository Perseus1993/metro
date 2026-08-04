using System;
using System.Collections.Generic;
using UnityEngine;

namespace MetroReplay.Presentation
{
    internal static class BrandIntroCoinMesh
    {
        public static Mesh Create(float radius, float thickness, int segments = 96)
        {
            if (radius <= 0f)
                throw new ArgumentOutOfRangeException(nameof(radius));
            if (thickness <= 0f)
                throw new ArgumentOutOfRangeException(nameof(thickness));
            if (segments < 12)
                throw new ArgumentOutOfRangeException(nameof(segments));

            var vertices = new List<Vector3>(segments * 8);
            var normals = new List<Vector3>(segments * 8);
            var uvs = new List<Vector2>(segments * 8);
            var edgeTriangles = new List<int>(segments * 18);
            var frontTriangles = new List<int>(segments * 3);
            var backTriangles = new List<int>(segments * 3);
            var halfThickness = thickness * 0.5f;
            var faceRadius = radius * 0.94f;

            AddFace(
                vertices,
                normals,
                uvs,
                frontTriangles,
                faceRadius,
                -halfThickness,
                -Vector3.forward,
                segments,
                false);
            AddFace(
                vertices,
                normals,
                uvs,
                backTriangles,
                faceRadius,
                halfThickness,
                Vector3.forward,
                segments,
                true);

            var bevel = Mathf.Min(thickness * 0.30f, radius * 0.06f);
            var profile = new[]
            {
                new Vector2(faceRadius, -halfThickness),
                new Vector2(radius, -halfThickness + bevel),
                new Vector2(radius, halfThickness - bevel),
                new Vector2(faceRadius, halfThickness)
            };
            AddEdge(vertices, normals, uvs, edgeTriangles, profile, segments);

            var mesh = new Mesh { name = "GenWorld brand intro coin" };
            mesh.SetVertices(vertices);
            mesh.SetNormals(normals);
            mesh.SetUVs(0, uvs);
            mesh.subMeshCount = 3;
            mesh.SetTriangles(edgeTriangles, 0, false);
            mesh.SetTriangles(frontTriangles, 1, false);
            mesh.SetTriangles(backTriangles, 2, false);
            mesh.RecalculateBounds();
            mesh.RecalculateTangents();
            return mesh;
        }

        public static Mesh CreateTorus(
            float majorRadius,
            float tubeRadius,
            int ringSegments = 96,
            int tubeSegments = 10)
        {
            if (majorRadius <= 0f || tubeRadius <= 0f)
                throw new ArgumentOutOfRangeException(nameof(majorRadius));
            if (ringSegments < 12 || tubeSegments < 4)
                throw new ArgumentOutOfRangeException(nameof(ringSegments));

            var vertices = new List<Vector3>((ringSegments + 1) * (tubeSegments + 1));
            var normals = new List<Vector3>(vertices.Capacity);
            var uvs = new List<Vector2>(vertices.Capacity);
            var triangles = new List<int>(ringSegments * tubeSegments * 6);

            for (var ring = 0; ring <= ringSegments; ring++)
            {
                var u = ring / (float)ringSegments;
                var ringAngle = u * Mathf.PI * 2f;
                var radial = new Vector3(Mathf.Cos(ringAngle), Mathf.Sin(ringAngle), 0f);
                for (var tube = 0; tube <= tubeSegments; tube++)
                {
                    var v = tube / (float)tubeSegments;
                    var tubeAngle = v * Mathf.PI * 2f;
                    var normal = radial * Mathf.Cos(tubeAngle) + Vector3.forward * Mathf.Sin(tubeAngle);
                    vertices.Add(radial * (majorRadius + tubeRadius * Mathf.Cos(tubeAngle))
                                 + Vector3.forward * tubeRadius * Mathf.Sin(tubeAngle));
                    normals.Add(normal.normalized);
                    uvs.Add(new Vector2(u, v));
                }
            }

            var stride = tubeSegments + 1;
            for (var ring = 0; ring < ringSegments; ring++)
            {
                for (var tube = 0; tube < tubeSegments; tube++)
                {
                    var current = ring * stride + tube;
                    var next = current + stride;
                    triangles.Add(current);
                    triangles.Add(next + 1);
                    triangles.Add(next);
                    triangles.Add(current);
                    triangles.Add(current + 1);
                    triangles.Add(next + 1);
                }
            }

            var mesh = new Mesh { name = "GenWorld brand intro luminous rim" };
            mesh.SetVertices(vertices);
            mesh.SetNormals(normals);
            mesh.SetUVs(0, uvs);
            mesh.SetTriangles(triangles, 0);
            mesh.RecalculateBounds();
            mesh.RecalculateTangents();
            return mesh;
        }

        private static void AddFace(
            ICollection<Vector3> vertices,
            ICollection<Vector3> normals,
            ICollection<Vector2> uvs,
            ICollection<int> triangles,
            float radius,
            float z,
            Vector3 normal,
            int segments,
            bool mirrorU)
        {
            var centerIndex = vertices.Count;
            vertices.Add(new Vector3(0f, 0f, z));
            normals.Add(normal);
            uvs.Add(new Vector2(0.5f, 0.5f));

            for (var i = 0; i <= segments; i++)
            {
                var angle = i / (float)segments * Mathf.PI * 2f;
                var x = Mathf.Cos(angle) * radius;
                var y = Mathf.Sin(angle) * radius;
                vertices.Add(new Vector3(x, y, z));
                normals.Add(normal);
                var u = 0.5f + x / (radius * 2f);
                if (mirrorU)
                    u = 1f - u;
                uvs.Add(new Vector2(u, 0.5f + y / (radius * 2f)));
            }

            for (var i = 0; i < segments; i++)
            {
                if (normal.z < 0f)
                {
                    triangles.Add(centerIndex);
                    triangles.Add(centerIndex + i + 2);
                    triangles.Add(centerIndex + i + 1);
                }
                else
                {
                    triangles.Add(centerIndex);
                    triangles.Add(centerIndex + i + 1);
                    triangles.Add(centerIndex + i + 2);
                }
            }
        }

        private static void AddEdge(
            ICollection<Vector3> vertices,
            ICollection<Vector3> normals,
            ICollection<Vector2> uvs,
            ICollection<int> triangles,
            IReadOnlyList<Vector2> profile,
            int segments)
        {
            var start = vertices.Count;
            for (var profileIndex = 0; profileIndex < profile.Count; profileIndex++)
            {
                var previous = profile[Mathf.Max(0, profileIndex - 1)];
                var next = profile[Mathf.Min(profile.Count - 1, profileIndex + 1)];
                var tangent = next - previous;
                var profileNormal = new Vector2(tangent.y, -tangent.x).normalized;
                for (var i = 0; i <= segments; i++)
                {
                    var u = i / (float)segments;
                    var angle = u * Mathf.PI * 2f;
                    var radial = new Vector3(Mathf.Cos(angle), Mathf.Sin(angle), 0f);
                    vertices.Add(radial * profile[profileIndex].x + Vector3.forward * profile[profileIndex].y);
                    normals.Add((radial * profileNormal.x + Vector3.forward * profileNormal.y).normalized);
                    uvs.Add(new Vector2(u, profileIndex / (float)(profile.Count - 1)));
                }
            }

            var stride = segments + 1;
            for (var profileIndex = 0; profileIndex < profile.Count - 1; profileIndex++)
            {
                for (var i = 0; i < segments; i++)
                {
                    var current = start + profileIndex * stride + i;
                    var next = current + stride;
                    triangles.Add(current);
                    triangles.Add(next);
                    triangles.Add(next + 1);
                    triangles.Add(current);
                    triangles.Add(next + 1);
                    triangles.Add(current + 1);
                }
            }
        }
    }
}
