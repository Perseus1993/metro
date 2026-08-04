using System;
using System.Collections.Generic;
using MetroReplay.Domain;
using UnityEngine;
using UnityEngine.Rendering.HighDefinition;

namespace MetroReplay.Presentation
{
    public sealed class StationSceneBuilder
    {
        private const float RoomFloorOffset = 0.03f;
        private const float RoomWallHeight = 2.6f;
        private const float RoomWallThickness = 0.12f;
        private const float RoomDoorHeight = 2.18f;
        private const float RoomRoofThickness = 0.06f;

        private readonly Transform _parent;
        private readonly StationFacilityModelBuilder _facilityModels;
        private readonly Dictionary<string, Material> _materials = new Dictionary<string, Material>();
        private Bounds _bounds;
        private bool _hasBounds;

        public StationSceneBuilder(Transform parent)
        {
            _parent = parent;
            _facilityModels = new StationFacilityModelBuilder(parent);
        }

        public Bounds Build(ReplayData data)
        {
            foreach (var level in data.Levels)
                BuildLevel(data, level);

            foreach (var entity in data.Entities)
            {
                if (entity.LevelIds.Count > 1 && IsVerticalConnector(entity.Kind))
                    BuildVerticalConnector(data, entity);
                else if (entity.LevelIds.Count > 0)
                    BuildSingleLevelEntity(data, entity);
            }

            return _hasBounds ? _bounds : new Bounds(Vector3.zero, Vector3.one * 10f);
        }

        private void BuildLevel(ReplayData data, ReplayLevel level)
        {
            var points = new List<Vector3>(level.Footprint.Count);
            foreach (var point in level.Footprint)
                points.Add(data.ToWorld(point.x, point.y, level.Id));
            var floor = BuildExtrudedPolygon($"Level_{level.Id}", points, 0.18f, MaterialForLevel(level));
            floor.transform.SetParent(_parent, true);
            Encapsulate(floor);
        }

        private void BuildSingleLevelEntity(ReplayData data, ReplayEntity entity)
        {
            var levelId = entity.LevelIds[0];
            var level = data.GetLevel(levelId);
            var geometry = entity.Geometry;
            if (string.Equals(entity.Kind, "walkable_area", StringComparison.OrdinalIgnoreCase))
            {
                if (geometry.Points.Count < 3)
                    return;
                var points = new List<Vector3>(geometry.Points.Count);
                foreach (var point in geometry.Points)
                    points.Add(data.ToWorld(point.x, point.y, levelId, 0.04f));
                var area = BuildFlatPolygon(entity.Id, points, 0.025f, MaterialFor("walkable", new Color(0.24f, 0.31f, 0.37f, 1f)));
                area.transform.SetParent(_parent, true);
                Encapsulate(area);
                return;
            }

            var flat = string.Equals(entity.Kind, "queue:lane", StringComparison.OrdinalIgnoreCase)
                || string.Equals(entity.Kind, "queue:grid", StringComparison.OrdinalIgnoreCase);
            var center = data.ToWorld(geometry.Center.x, geometry.Center.y, levelId, flat ? 0.08f : 0.45f);
            GetPlanarSize(data, geometry, levelId, out var sizeX, out var sizeZ);
            sizeX = Mathf.Max(sizeX, 0.35f);
            sizeZ = Mathf.Max(sizeZ, 0.35f);

            var baseCenter = data.ToWorld(geometry.Center.x, geometry.Center.y, levelId, 0.10f);
            if (_facilityModels.TryBuildPlanar(
                entity.Kind, entity.Id, baseCenter, sizeX, sizeZ,
                geometry.RotationDegrees, out var facility))
            {
                Encapsulate(facility);
                return;
            }

            if (IsRoomBlock(entity))
            {
                var roomCenter = data.ToWorld(
                    geometry.Center.x, geometry.Center.y, levelId, RoomFloorOffset);
                var room = BuildRoomShell(
                    entity.Id, roomCenter, sizeX, sizeZ, geometry.RotationDegrees);
                Encapsulate(room);
                return;
            }

            var height = HeightFor(entity.Kind);
            var gameObject = GameObject.CreatePrimitive(PrimitiveType.Cube);
            gameObject.name = entity.Id;
            gameObject.transform.SetParent(_parent, true);
            gameObject.transform.position = center + Vector3.up * Mathf.Max(0f, (height - 0.9f) * 0.5f);
            gameObject.transform.rotation = Quaternion.Euler(0f, -geometry.RotationDegrees, 0f);
            gameObject.transform.localScale = new Vector3(sizeX, height, sizeZ);
            RemoveCollider(gameObject);
            gameObject.GetComponent<Renderer>().sharedMaterial = MaterialForKind(entity.Kind);
            Encapsulate(gameObject);

        }

        private GameObject BuildRoomShell(
            string name,
            Vector3 center,
            float sizeX,
            float sizeZ,
            float rotationDegrees)
        {
            var room = new GameObject(name);
            room.transform.SetParent(_parent, true);
            room.transform.SetPositionAndRotation(
                center,
                Quaternion.Euler(0f, -rotationDegrees, 0f));

            var wallMaterial = MaterialFor(
                "room-wall",
                new Color(0.24f, 0.31f, 0.39f, 1f));
            var roofMaterial = MaterialFor(
                "room-cutaway-roof",
                new Color(0.45f, 0.58f, 0.70f, 0.20f),
                true);
            var halfX = sizeX * 0.5f;
            var halfZ = sizeZ * 0.5f;
            var sideDepth = Mathf.Max(RoomWallThickness, sizeZ - RoomWallThickness * 2f);
            var sideWidth = Mathf.Max(RoomWallThickness, sizeX - RoomWallThickness * 2f);
            var doorWallRunsAlongX = sizeX >= sizeZ;

            if (doorWallRunsAlongX)
            {
                AddRoomPart(room.transform, "Wall_Back",
                    new Vector3(0f, RoomWallHeight * 0.5f, halfZ),
                    new Vector3(sizeX, RoomWallHeight, RoomWallThickness), wallMaterial);
                AddRoomPart(room.transform, "Wall_Left",
                    new Vector3(-halfX, RoomWallHeight * 0.5f, 0f),
                    new Vector3(RoomWallThickness, RoomWallHeight, sideDepth), wallMaterial);
                AddRoomPart(room.transform, "Wall_Right",
                    new Vector3(halfX, RoomWallHeight * 0.5f, 0f),
                    new Vector3(RoomWallThickness, RoomWallHeight, sideDepth), wallMaterial);
                AddDoorWallAlongX(room.transform, sizeX, -halfZ, wallMaterial);
            }
            else
            {
                AddRoomPart(room.transform, "Wall_Back",
                    new Vector3(halfX, RoomWallHeight * 0.5f, 0f),
                    new Vector3(RoomWallThickness, RoomWallHeight, sizeZ), wallMaterial);
                AddRoomPart(room.transform, "Wall_Left",
                    new Vector3(0f, RoomWallHeight * 0.5f, -halfZ),
                    new Vector3(sideWidth, RoomWallHeight, RoomWallThickness), wallMaterial);
                AddRoomPart(room.transform, "Wall_Right",
                    new Vector3(0f, RoomWallHeight * 0.5f, halfZ),
                    new Vector3(sideWidth, RoomWallHeight, RoomWallThickness), wallMaterial);
                AddDoorWallAlongZ(room.transform, sizeZ, -halfX, wallMaterial);
            }

            AddRoomPart(room.transform, "CutawayRoof",
                new Vector3(0f, RoomWallHeight + RoomRoofThickness * 0.5f, 0f),
                new Vector3(sizeX + 0.08f, RoomRoofThickness, sizeZ + 0.08f),
                roofMaterial);
            return room;
        }

        private static void AddDoorWallAlongX(
            Transform parent, float wallLength, float z, Material material)
        {
            var doorWidth = DoorWidthFor(wallLength);
            var segmentLength = Mathf.Max(
                RoomWallThickness,
                (wallLength - doorWidth) * 0.5f);
            var segmentCenter = doorWidth * 0.5f + segmentLength * 0.5f;
            AddRoomPart(parent, "Wall_DoorLeft",
                new Vector3(-segmentCenter, RoomWallHeight * 0.5f, z),
                new Vector3(segmentLength, RoomWallHeight, RoomWallThickness), material);
            AddRoomPart(parent, "Wall_DoorRight",
                new Vector3(segmentCenter, RoomWallHeight * 0.5f, z),
                new Vector3(segmentLength, RoomWallHeight, RoomWallThickness), material);
            AddRoomPart(parent, "Wall_DoorHeader",
                new Vector3(0f, RoomDoorHeight + (RoomWallHeight - RoomDoorHeight) * 0.5f, z),
                new Vector3(doorWidth, RoomWallHeight - RoomDoorHeight, RoomWallThickness), material);
        }

        private static void AddDoorWallAlongZ(
            Transform parent, float wallLength, float x, Material material)
        {
            var doorWidth = DoorWidthFor(wallLength);
            var segmentLength = Mathf.Max(
                RoomWallThickness,
                (wallLength - doorWidth) * 0.5f);
            var segmentCenter = doorWidth * 0.5f + segmentLength * 0.5f;
            AddRoomPart(parent, "Wall_DoorLeft",
                new Vector3(x, RoomWallHeight * 0.5f, -segmentCenter),
                new Vector3(RoomWallThickness, RoomWallHeight, segmentLength), material);
            AddRoomPart(parent, "Wall_DoorRight",
                new Vector3(x, RoomWallHeight * 0.5f, segmentCenter),
                new Vector3(RoomWallThickness, RoomWallHeight, segmentLength), material);
            AddRoomPart(parent, "Wall_DoorHeader",
                new Vector3(x, RoomDoorHeight + (RoomWallHeight - RoomDoorHeight) * 0.5f, 0f),
                new Vector3(RoomWallThickness, RoomWallHeight - RoomDoorHeight, doorWidth), material);
        }

        private static float DoorWidthFor(float wallLength)
        {
            var preferred = Mathf.Clamp(wallLength * 0.24f, 1.2f, 1.8f);
            return Mathf.Max(
                RoomWallThickness,
                Mathf.Min(preferred, wallLength - RoomWallThickness * 3f));
        }

        private static GameObject AddRoomPart(
            Transform parent,
            string name,
            Vector3 localPosition,
            Vector3 size,
            Material material)
        {
            var part = GameObject.CreatePrimitive(PrimitiveType.Cube);
            part.name = name;
            part.transform.SetParent(parent, false);
            part.transform.localPosition = localPosition;
            part.transform.localScale = size;
            RemoveCollider(part);
            part.GetComponent<Renderer>().sharedMaterial = material;
            return part;
        }

        private void BuildVerticalConnector(ReplayData data, ReplayEntity entity)
        {
            if (entity.Geometry.Points.Count < 2 || entity.LevelIds.Count < 2)
                return;

            var startPoint = entity.Geometry.Points[0];
            var endPoint = entity.Geometry.Points[entity.Geometry.Points.Count - 1];
            var start = data.ToWorld(startPoint.x, startPoint.y, entity.LevelIds[0], 0.15f);
            var end = data.ToWorld(endPoint.x, endPoint.y, entity.LevelIds[entity.LevelIds.Count - 1], 0.15f);
            var connector = _facilityModels.BuildVertical(entity.Kind, entity.Id, start, end);
            Encapsulate(connector);
        }

        private static GameObject BuildFlatPolygon(string name, IReadOnlyList<Vector3> points, float thickness, Material material)
        {
            var gameObject = new GameObject(name);
            var filter = gameObject.AddComponent<MeshFilter>();
            var renderer = gameObject.AddComponent<MeshRenderer>();
            renderer.sharedMaterial = material;

            var vertices = new Vector3[points.Count];
            for (var i = 0; i < points.Count; i++)
                vertices[i] = points[i] + Vector3.down * (thickness * 0.5f);
            var triangles = TriangulateXZ(vertices);
            var mesh = new Mesh { name = name + "_Mesh" };
            mesh.vertices = vertices;
            mesh.triangles = triangles;
            mesh.RecalculateNormals();
            mesh.RecalculateBounds();
            filter.sharedMesh = mesh;
            return gameObject;
        }

        private static GameObject BuildExtrudedPolygon(
            string name,
            IReadOnlyList<Vector3> points,
            float thickness,
            Material material)
        {
            var gameObject = new GameObject(name);
            var filter = gameObject.AddComponent<MeshFilter>();
            var renderer = gameObject.AddComponent<MeshRenderer>();
            renderer.sharedMaterial = material;

            var pointCount = points.Count;
            var vertices = new Vector3[pointCount * 2];
            for (var i = 0; i < pointCount; i++)
            {
                vertices[i] = points[i];
                vertices[pointCount + i] = points[i] + Vector3.down * thickness;
            }

            var surface = TriangulateXZ(points);
            var triangles = new List<int>(surface.Length * 2 + pointCount * 6);
            for (var i = 0; i < surface.Length; i += 3)
            {
                // TriangulateXZ returns downward-facing XZ triangles. Reverse them
                // for the walkable top and preserve them for the visible underside.
                triangles.Add(surface[i + 2]);
                triangles.Add(surface[i + 1]);
                triangles.Add(surface[i]);
                triangles.Add(pointCount + surface[i]);
                triangles.Add(pointCount + surface[i + 1]);
                triangles.Add(pointCount + surface[i + 2]);
            }

            var clockwise = SignedAreaXZ(points) < 0f;
            for (var i = 0; i < pointCount; i++)
            {
                var next = (i + 1) % pointCount;
                if (clockwise)
                {
                    triangles.Add(i);
                    triangles.Add(pointCount + next);
                    triangles.Add(next);
                    triangles.Add(i);
                    triangles.Add(pointCount + i);
                    triangles.Add(pointCount + next);
                }
                else
                {
                    triangles.Add(i);
                    triangles.Add(next);
                    triangles.Add(pointCount + next);
                    triangles.Add(i);
                    triangles.Add(pointCount + next);
                    triangles.Add(pointCount + i);
                }
            }

            var mesh = new Mesh { name = name + "_Mesh" };
            mesh.vertices = vertices;
            mesh.triangles = triangles.ToArray();
            mesh.RecalculateNormals();
            mesh.RecalculateBounds();
            filter.sharedMesh = mesh;
            return gameObject;
        }

        private static float SignedAreaXZ(IReadOnlyList<Vector3> points)
        {
            var area = 0f;
            for (var i = 0; i < points.Count; i++)
            {
                var next = (i + 1) % points.Count;
                area += points[i].x * points[next].z - points[next].x * points[i].z;
            }
            return area;
        }

        private static int[] TriangulateXZ(IReadOnlyList<Vector3> points)
        {
            // Scene contract footprints are simple polygons. Ear clipping also handles
            // the concave walkable polygons emitted by the Python station designer.
            var remaining = new List<int>(points.Count);
            var signedArea = 0f;
            for (var i = 0; i < points.Count; i++)
            {
                var next = (i + 1) % points.Count;
                signedArea += points[i].x * points[next].z - points[next].x * points[i].z;
            }
            if (signedArea > 0f)
            {
                for (var i = 0; i < points.Count; i++)
                    remaining.Add(i);
            }
            else
            {
                for (var i = points.Count - 1; i >= 0; i--)
                    remaining.Add(i);
            }

            var triangles = new List<int>((points.Count - 2) * 3);
            var guard = points.Count * points.Count;
            while (remaining.Count > 2 && guard-- > 0)
            {
                var clipped = false;
                for (var i = 0; i < remaining.Count; i++)
                {
                    var previous = remaining[(i - 1 + remaining.Count) % remaining.Count];
                    var current = remaining[i];
                    var next = remaining[(i + 1) % remaining.Count];
                    if (!IsConvex(points[previous], points[current], points[next]))
                        continue;
                    if (ContainsAnyPoint(points, remaining, previous, current, next))
                        continue;
                    triangles.Add(previous);
                    triangles.Add(current);
                    triangles.Add(next);
                    remaining.RemoveAt(i);
                    clipped = true;
                    break;
                }
                if (!clipped)
                    break;
            }

            if (triangles.Count == (points.Count - 2) * 3)
                return triangles.ToArray();

            // Defensive fallback for malformed/self-intersecting display geometry.
            triangles.Clear();
            for (var i = 1; i < points.Count - 1; i++)
            {
                triangles.Add(0);
                triangles.Add(i);
                triangles.Add(i + 1);
            }
            return triangles.ToArray();
        }

        private static bool IsConvex(Vector3 a, Vector3 b, Vector3 c)
        {
            var ab = new Vector2(b.x - a.x, b.z - a.z);
            var bc = new Vector2(c.x - b.x, c.z - b.z);
            return ab.x * bc.y - ab.y * bc.x > 0.00001f;
        }

        private static bool ContainsAnyPoint(
            IReadOnlyList<Vector3> points,
            IReadOnlyList<int> indices,
            int a,
            int b,
            int c)
        {
            foreach (var index in indices)
            {
                if (index == a || index == b || index == c)
                    continue;
                if (PointInTriangle(points[index], points[a], points[b], points[c]))
                    return true;
            }
            return false;
        }

        private static bool PointInTriangle(Vector3 point, Vector3 a, Vector3 b, Vector3 c)
        {
            var p = new Vector2(point.x, point.z);
            var p0 = new Vector2(a.x, a.z);
            var p1 = new Vector2(b.x, b.z);
            var p2 = new Vector2(c.x, c.z);
            var d1 = Sign(p, p0, p1);
            var d2 = Sign(p, p1, p2);
            var d3 = Sign(p, p2, p0);
            var hasNegative = d1 < 0f || d2 < 0f || d3 < 0f;
            var hasPositive = d1 > 0f || d2 > 0f || d3 > 0f;
            return !(hasNegative && hasPositive);
        }

        private static float Sign(Vector2 p1, Vector2 p2, Vector2 p3)
        {
            return (p1.x - p3.x) * (p2.y - p3.y) - (p2.x - p3.x) * (p1.y - p3.y);
        }

        private void GetPlanarSize(ReplayData data, ReplayGeometry geometry, string levelId, out float sizeX, out float sizeZ)
        {
            sizeX = Mathf.Abs(geometry.Width);
            sizeZ = Mathf.Abs(geometry.Height);
            if (sizeX > 0f || sizeZ > 0f || geometry.Points.Count == 0)
                return;

            var min = new Vector2(float.PositiveInfinity, float.PositiveInfinity);
            var max = new Vector2(float.NegativeInfinity, float.NegativeInfinity);
            foreach (var point in geometry.Points)
            {
                var world = data.ToWorld(point.x, point.y, levelId);
                min = Vector2.Min(min, new Vector2(world.x, world.z));
                max = Vector2.Max(max, new Vector2(world.x, world.z));
            }
            sizeX = max.x - min.x;
            sizeZ = max.y - min.y;
        }

        private Material MaterialForLevel(ReplayLevel level)
        {
            var color = level.Elevation > -10f
                ? new Color(0.12f, 0.20f, 0.28f)
                : new Color(0.16f, 0.24f, 0.31f);
            return MaterialFor("level-" + level.Id, color);
        }

        private Material MaterialForKind(string kind)
        {
            switch (kind.ToLowerInvariant())
            {
                case "entrance": return MaterialFor("entrance", new Color(0.20f, 0.72f, 0.48f));
                case "gate": return MaterialFor("gate", new Color(0.16f, 0.53f, 0.90f));
                case "escalator": return MaterialFor("escalator", new Color(0.95f, 0.61f, 0.17f));
                case "elevator": return MaterialFor("elevator", new Color(0.22f, 0.78f, 0.87f));
                case "stairs": return MaterialFor("stairs", new Color(0.62f, 0.50f, 0.87f));
                case "platform_edge": return MaterialFor("platform", new Color(0.96f, 0.33f, 0.27f));
                case "queue:lane":
                case "queue:grid": return MaterialFor("queue", new Color(0.20f, 0.66f, 0.62f, 0.30f), true);
                case "obstacle": return MaterialFor("obstacle", new Color(0.35f, 0.38f, 0.42f));
                default: return MaterialFor("default", new Color(0.55f, 0.59f, 0.64f));
            }
        }

        private Material MaterialFor(string key, Color color, bool transparent = false)
        {
            if (_materials.TryGetValue(key, out var material))
                return material;
            material = ReplayMaterialFactory.Create("MetroReplay_" + key, color);
            if (transparent)
            {
                material.SetFloat("_SurfaceType", 1f);
                material.SetFloat("_BlendMode", 0f);
                material.SetFloat("_TransparentZWrite", 0f);
                HDMaterial.ValidateMaterial(material);
            }
            _materials[key] = material;
            return material;
        }

        private static float HeightFor(string kind)
        {
            switch (kind.ToLowerInvariant())
            {
                case "queue:lane":
                case "queue:grid": return 0.03f;
                case "platform_edge": return 0.35f;
                case "obstacle": return 0.8f;
                case "gate": return 1.1f;
                case "entrance": return 2.3f;
                default: return 0.75f;
            }
        }

        private static bool IsVerticalConnector(string kind)
        {
            return string.Equals(kind, "escalator", StringComparison.OrdinalIgnoreCase)
                || string.Equals(kind, "elevator", StringComparison.OrdinalIgnoreCase)
                || string.Equals(kind, "stairs", StringComparison.OrdinalIgnoreCase);
        }

        private static bool IsRoomBlock(ReplayEntity entity)
        {
            if (!string.Equals(entity.Kind, "obstacle", StringComparison.OrdinalIgnoreCase))
                return false;
            var label = entity.Label ?? string.Empty;
            return label.IndexOf("service center", StringComparison.OrdinalIgnoreCase) >= 0
                || label.IndexOf("restroom", StringComparison.OrdinalIgnoreCase) >= 0
                || label.IndexOf("shop", StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private static void RemoveCollider(GameObject gameObject)
        {
            var collider = gameObject.GetComponent<Collider>();
            if (collider != null)
            {
                if (UnityEngine.Application.isPlaying)
                    UnityEngine.Object.Destroy(collider);
                else
                    UnityEngine.Object.DestroyImmediate(collider);
            }
        }

        private void Encapsulate(GameObject gameObject)
        {
            foreach (var renderer in gameObject.GetComponentsInChildren<Renderer>(true))
            {
                if (!_hasBounds)
                {
                    _bounds = renderer.bounds;
                    _hasBounds = true;
                }
                else
                {
                    _bounds.Encapsulate(renderer.bounds);
                }
            }
        }
    }
}
