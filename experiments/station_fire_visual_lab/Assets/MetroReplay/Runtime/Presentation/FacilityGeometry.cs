using System.Collections.Generic;
using UnityEngine;

namespace MetroReplay.Presentation
{
    internal static class FacilityGeometry
    {
        public static GameObject Box(
            Transform parent, string name, Vector3 position, Vector3 size, Material material)
        {
            var item = GameObject.CreatePrimitive(PrimitiveType.Cube);
            item.name = name;
            item.transform.SetParent(parent, false);
            item.transform.localPosition = position;
            item.transform.localScale = size;
            RemoveCollider(item);
            item.GetComponent<Renderer>().sharedMaterial = material;
            return item;
        }

        public static GameObject RoundedPrism(
            Transform parent, string name, Vector3 position, Vector3 size,
            float radius, Material material)
        {
            var item = new GameObject(name);
            item.transform.SetParent(parent, false);
            item.transform.localPosition = position;
            var filter = item.AddComponent<MeshFilter>();
            var renderer = item.AddComponent<MeshRenderer>();
            renderer.sharedMaterial = material;
            filter.sharedMesh = BuildRoundedPrismMesh(name + "_Mesh", size, radius);
            return item;
        }

        public static GameObject Rail(
            Transform parent, string name, Vector3 start, Vector3 end,
            float diameter, Material material)
        {
            var delta = end - start;
            var item = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            item.name = name;
            item.transform.SetParent(parent, false);
            item.transform.localPosition = (start + end) * 0.5f;
            item.transform.localRotation = Quaternion.FromToRotation(Vector3.up, delta.normalized);
            item.transform.localScale = new Vector3(diameter, delta.magnitude * 0.5f, diameter);
            RemoveCollider(item);
            item.GetComponent<Renderer>().sharedMaterial = material;
            return item;
        }

        public static GameObject SlopedBox(
            Transform parent, string name, Vector3 start, Vector3 end,
            Vector2 crossSection, Material material)
        {
            var delta = end - start;
            var item = Box(parent, name, (start + end) * 0.5f,
                new Vector3(crossSection.x, crossSection.y, delta.magnitude), material);
            item.transform.localRotation = Quaternion.FromToRotation(Vector3.forward, delta.normalized);
            return item;
        }

        private static void RemoveCollider(GameObject item)
        {
            var collider = item.GetComponent<Collider>();
            if (collider == null)
                return;
            if (UnityEngine.Application.isEditor)
                Object.DestroyImmediate(collider);
            else
                Object.Destroy(collider);
        }

        private static Mesh BuildRoundedPrismMesh(string name, Vector3 size, float radius)
        {
            const int cornerSegments = 3;
            var ring = new List<Vector2>(cornerSegments * 4 + 4);
            var halfX = size.x * 0.5f;
            var halfZ = size.z * 0.5f;
            radius = Mathf.Clamp(radius, 0.01f, Mathf.Min(halfX, halfZ) * 0.95f);
            AddCorner(ring, new Vector2(halfX - radius, -halfZ + radius), radius, -90f, 0f, cornerSegments);
            AddCorner(ring, new Vector2(halfX - radius, halfZ - radius), radius, 0f, 90f, cornerSegments);
            AddCorner(ring, new Vector2(-halfX + radius, halfZ - radius), radius, 90f, 180f, cornerSegments);
            AddCorner(ring, new Vector2(-halfX + radius, -halfZ + radius), radius, 180f, 270f, cornerSegments);

            var count = ring.Count;
            var vertices = new Vector3[count * 2 + 2];
            var halfY = size.y * 0.5f;
            for (var i = 0; i < count; i++)
            {
                vertices[i] = new Vector3(ring[i].x, -halfY, ring[i].y);
                vertices[i + count] = new Vector3(ring[i].x, halfY, ring[i].y);
            }
            var bottomCenter = count * 2;
            var topCenter = bottomCenter + 1;
            vertices[bottomCenter] = new Vector3(0f, -halfY, 0f);
            vertices[topCenter] = new Vector3(0f, halfY, 0f);

            var triangles = new List<int>(count * 12);
            for (var i = 0; i < count; i++)
            {
                var next = (i + 1) % count;
                triangles.Add(i); triangles.Add(next); triangles.Add(next + count);
                triangles.Add(i); triangles.Add(next + count); triangles.Add(i + count);
                triangles.Add(bottomCenter); triangles.Add(next); triangles.Add(i);
                triangles.Add(topCenter); triangles.Add(i + count); triangles.Add(next + count);
            }

            var mesh = new Mesh { name = name, vertices = vertices, triangles = triangles.ToArray() };
            mesh.RecalculateNormals();
            mesh.RecalculateTangents();
            mesh.RecalculateBounds();
            return mesh;
        }

        private static void AddCorner(
            ICollection<Vector2> points, Vector2 center, float radius,
            float startDegrees, float endDegrees, int segments)
        {
            for (var i = 0; i <= segments; i++)
            {
                var angle = Mathf.Lerp(startDegrees, endDegrees, i / (float)segments) * Mathf.Deg2Rad;
                points.Add(center + new Vector2(Mathf.Cos(angle), Mathf.Sin(angle)) * radius);
            }
        }
    }
}
