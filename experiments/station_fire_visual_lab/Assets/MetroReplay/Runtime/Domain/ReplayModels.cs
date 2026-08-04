using System;
using System.Collections.Generic;
using UnityEngine;

namespace MetroReplay.Domain
{
    public sealed class ReplayLevel
    {
        public string Id { get; }
        public string Label { get; }
        public float Elevation { get; }
        public IReadOnlyList<Vector2> Footprint { get; }
        public Vector2 SourceOrigin { get; }

        public ReplayLevel(string id, string label, float elevation, IReadOnlyList<Vector2> footprint)
        {
            Id = id;
            Label = label;
            Elevation = elevation;
            Footprint = footprint;

            var minX = float.PositiveInfinity;
            var minY = float.PositiveInfinity;
            foreach (var point in footprint)
            {
                minX = Mathf.Min(minX, point.x);
                minY = Mathf.Min(minY, point.y);
            }

            SourceOrigin = new Vector2(
                float.IsInfinity(minX) ? 0f : minX,
                float.IsInfinity(minY) ? 0f : minY);
        }
    }

    public sealed class ReplayGeometry
    {
        public string Shape { get; }
        public float X { get; }
        public float Y { get; }
        public float Width { get; }
        public float Height { get; }
        public float RotationDegrees { get; }
        public IReadOnlyList<Vector2> Points { get; }

        public ReplayGeometry(
            string shape,
            float x,
            float y,
            float width,
            float height,
            float rotationDegrees,
            IReadOnlyList<Vector2> points)
        {
            Shape = shape;
            X = x;
            Y = y;
            Width = width;
            Height = height;
            RotationDegrees = rotationDegrees;
            Points = points;
        }

        public Vector2 Center
        {
            get
            {
                if (Width > 0f || Height > 0f)
                    return new Vector2(X, Y);
                if (Points.Count == 0)
                    return Vector2.zero;

                var sum = Vector2.zero;
                foreach (var point in Points)
                    sum += point;
                return sum / Points.Count;
            }
        }
    }

    public sealed class ReplayEntity
    {
        public string Id { get; }
        public string Kind { get; }
        public string Label { get; }
        public ReplayGeometry Geometry { get; }
        public IReadOnlyList<string> LevelIds { get; }

        public ReplayEntity(
            string id,
            string kind,
            string label,
            ReplayGeometry geometry,
            IReadOnlyList<string> levelIds)
        {
            Id = id;
            Kind = kind;
            Label = label;
            Geometry = geometry;
            LevelIds = levelIds;
        }
    }

    public sealed class PassengerSnapshot
    {
        public int Id { get; }
        public float X { get; }
        public float Y { get; }
        public string LevelId { get; }
        public string State { get; }
        public string Intent { get; }
        public int Persons { get; }

        public PassengerSnapshot(
            int id,
            float x,
            float y,
            string levelId,
            string state,
            string intent,
            int persons)
        {
            Id = id;
            X = x;
            Y = y;
            LevelId = levelId;
            State = state;
            Intent = intent;
            Persons = persons;
        }
    }

    public sealed class TrainSnapshot
    {
        public int Id { get; }
        public string LineId { get; }
        public string Direction { get; }
        public string PlatformId { get; }
        public string State { get; }
        public int CurrentLoadPersons { get; }
        public int LastDepartedLoadPersons { get; }
        public float? DepartureElapsedSeconds { get; }
        public int DepartedTrains { get; }
        public int CancelledTrains { get; }
        public float NextArrivalSeconds { get; }
        public bool ServiceSuspended { get; }
        public int CapacityPersons { get; }

        public TrainSnapshot(
            int id,
            string lineId,
            string direction,
            string platformId,
            string state,
            int currentLoadPersons,
            int lastDepartedLoadPersons,
            float? departureElapsedSeconds,
            int departedTrains,
            int cancelledTrains,
            float nextArrivalSeconds,
            bool serviceSuspended,
            int capacityPersons)
        {
            Id = id;
            LineId = lineId;
            Direction = direction;
            PlatformId = platformId;
            State = state;
            CurrentLoadPersons = currentLoadPersons;
            LastDepartedLoadPersons = lastDepartedLoadPersons;
            DepartureElapsedSeconds = departureElapsedSeconds;
            DepartedTrains = departedTrains;
            CancelledTrains = cancelledTrains;
            NextArrivalSeconds = nextArrivalSeconds;
            ServiceSuspended = serviceSuspended;
            CapacityPersons = capacityPersons;
        }
    }

    public sealed class ReplayFrame
    {
        public float Time { get; }
        public IReadOnlyDictionary<int, PassengerSnapshot> Passengers { get; }
        public IReadOnlyDictionary<int, TrainSnapshot> Trains { get; }

        public ReplayFrame(
            float time,
            IReadOnlyDictionary<int, PassengerSnapshot> passengers,
            IReadOnlyDictionary<int, TrainSnapshot> trains)
        {
            Time = time;
            Passengers = passengers;
            Trains = trains;
        }
    }

    public sealed class FacilityServiceEvent
    {
        public int EventId { get; }
        public string FacilityId { get; }
        public string FacilityKind { get; }
        public IReadOnlyList<int> PassengerIds { get; }
        public float StartTime { get; }
        public float BoardEndTime { get; }
        public float ArriveTime { get; }
        public float EndTime { get; }
        public Vector2 StartPosition { get; }
        public Vector2 EndPosition { get; }
        public string FromLevel { get; }
        public string ToLevel { get; }

        public FacilityServiceEvent(
            int eventId,
            string facilityId,
            string facilityKind,
            IReadOnlyList<int> passengerIds,
            float startTime,
            float boardEndTime,
            float arriveTime,
            float endTime,
            Vector2 startPosition,
            Vector2 endPosition,
            string fromLevel,
            string toLevel)
        {
            EventId = eventId;
            FacilityId = facilityId;
            FacilityKind = facilityKind;
            PassengerIds = passengerIds;
            StartTime = startTime;
            BoardEndTime = boardEndTime;
            ArriveTime = arriveTime;
            EndTime = endTime;
            StartPosition = startPosition;
            EndPosition = endPosition;
            FromLevel = fromLevel;
            ToLevel = toLevel;
        }

        public bool ContainsPassenger(int passengerId)
        {
            for (var i = 0; i < PassengerIds.Count; i++)
            {
                if (PassengerIds[i] == passengerId)
                    return true;
            }
            return false;
        }
    }

    public sealed class ReplayClearanceAudit
    {
        public bool IsAvailable { get; }
        public bool Cleared { get; }
        public string Outcome { get; }
        public int TotalPassengers { get; }
        public int CompletedPassengers { get; }
        public int RemainingPassengers { get; }
        public float? ClearanceTime { get; }

        public ReplayClearanceAudit(
            bool isAvailable,
            bool cleared,
            string outcome,
            int totalPassengers,
            int completedPassengers,
            int remainingPassengers,
            float? clearanceTime)
        {
            IsAvailable = isAvailable;
            Cleared = cleared;
            Outcome = outcome;
            TotalPassengers = totalPassengers;
            CompletedPassengers = completedPassengers;
            RemainingPassengers = remainingPassengers;
            ClearanceTime = clearanceTime;
        }

        public static ReplayClearanceAudit Unavailable { get; } = new ReplayClearanceAudit(
            false,
            false,
            "unavailable",
            0,
            0,
            0,
            null);
    }

    public sealed class ReplayFidelity
    {
        public string PositionAuthority { get; }
        public float SnapshotIntervalSeconds { get; }
        public string FacilityMotionAuthority { get; }
        public bool VisualTracksAuthoritative { get; }
        public IReadOnlyList<string> RoutingPluginIds { get; }
        public int RoutingDecisionCount { get; }

        public bool IsAuthoritative =>
            string.Equals(
                PositionAuthority,
                "simulation_trace.snapshots",
                StringComparison.Ordinal)
            && !VisualTracksAuthoritative;

        public ReplayFidelity(
            string positionAuthority,
            float snapshotIntervalSeconds,
            string facilityMotionAuthority,
            bool visualTracksAuthoritative,
            IReadOnlyList<string> routingPluginIds,
            int routingDecisionCount)
        {
            PositionAuthority = positionAuthority ?? string.Empty;
            SnapshotIntervalSeconds = Mathf.Max(0f, snapshotIntervalSeconds);
            FacilityMotionAuthority = facilityMotionAuthority ?? string.Empty;
            VisualTracksAuthoritative = visualTracksAuthoritative;
            RoutingPluginIds = routingPluginIds ?? Array.Empty<string>();
            RoutingDecisionCount = Mathf.Max(0, routingDecisionCount);
        }

        public static ReplayFidelity Unspecified { get; } = new ReplayFidelity(
            string.Empty,
            0f,
            string.Empty,
            false,
            Array.Empty<string>(),
            0);
    }

    public sealed class ReplayData
    {
        private readonly Dictionary<string, ReplayLevel> _levelsById;
        private readonly Dictionary<string, Vector2> _levelPlanOffsets;

        public string RunId { get; }
        public IReadOnlyList<ReplayLevel> Levels { get; }
        public IReadOnlyList<ReplayEntity> Entities { get; }
        public IReadOnlyList<ReplayFrame> Frames { get; }
        public IReadOnlyList<FacilityServiceEvent> FacilityEvents { get; }
        public ReplayClearanceAudit ClearanceAudit { get; }
        public ReplayFidelity Fidelity { get; }
        public float Duration { get; }
        public int FinalVisiblePassengers { get; }

        public ReplayData(
            string runId,
            IReadOnlyList<ReplayLevel> levels,
            IReadOnlyList<ReplayEntity> entities,
            IReadOnlyList<ReplayFrame> frames,
            IReadOnlyList<FacilityServiceEvent> facilityEvents,
            ReplayClearanceAudit clearanceAudit,
            ReplayFidelity fidelity = null)
        {
            RunId = runId;
            Levels = levels;
            Entities = entities;
            Frames = frames;
            FacilityEvents = facilityEvents;
            ClearanceAudit = clearanceAudit ?? ReplayClearanceAudit.Unavailable;
            Fidelity = fidelity ?? ReplayFidelity.Unspecified;
            _levelsById = new Dictionary<string, ReplayLevel>(StringComparer.Ordinal);
            foreach (var level in levels)
                _levelsById[level.Id] = level;
            _levelPlanOffsets = BuildLevelPlanOffsets(levels, entities);

            Duration = frames.Count == 0 ? 0f : frames[frames.Count - 1].Time;
            foreach (var serviceEvent in facilityEvents)
                Duration = Mathf.Max(Duration, serviceEvent.EndTime);

            if (frames.Count > 0)
            {
                foreach (var passenger in frames[frames.Count - 1].Passengers.Values)
                    FinalVisiblePassengers += passenger.Persons;
            }
        }

        public ReplayLevel GetLevel(string levelId)
        {
            if (!string.IsNullOrEmpty(levelId) && _levelsById.TryGetValue(levelId, out var level))
                return level;
            if (Levels.Count == 0)
                throw new InvalidOperationException("Replay contains no levels.");
            return Levels[0];
        }

        public Vector3 ToWorld(float sourceX, float sourceY, string levelId, float heightOffset = 0f)
        {
            var level = GetLevel(levelId);
            var planOffset = _levelPlanOffsets.TryGetValue(level.Id, out var registeredOffset)
                ? registeredOffset
                : Vector2.zero;
            return new Vector3(
                sourceX - level.SourceOrigin.x + planOffset.x,
                level.Elevation + heightOffset,
                -(sourceY - level.SourceOrigin.y) + planOffset.y);
        }

        private static Dictionary<string, Vector2> BuildLevelPlanOffsets(
            IReadOnlyList<ReplayLevel> levels,
            IReadOnlyList<ReplayEntity> entities)
        {
            var result = new Dictionary<string, Vector2>(StringComparer.Ordinal);
            if (levels.Count == 0)
                return result;

            // The source station drawing lays floor plans out on one 2D canvas.  Each
            // level therefore has a different drawing origin even though its lift
            // shaft occupies the same physical X/Z position.  Register floors through
            // elevator shafts before projecting any geometry into the 3D scene.
            var reference = levels[0];
            for (var index = 1; index < levels.Count; index++)
            {
                if (levels[index].Elevation < reference.Elevation)
                    reference = levels[index];
            }

            result[reference.Id] = Vector2.zero;
            var unresolvedPasses = Mathf.Max(1, levels.Count - 1);
            for (var pass = 0; pass < unresolvedPasses; pass++)
            {
                var changed = false;
                foreach (var entity in entities)
                {
                    if (!string.Equals(entity.Kind, "elevator", StringComparison.OrdinalIgnoreCase)
                        || entity.LevelIds.Count < 2
                        || entity.Geometry.Points.Count < 2)
                    {
                        continue;
                    }

                    var firstLevel = FindLevel(levels, entity.LevelIds[0]);
                    var lastLevel = FindLevel(levels, entity.LevelIds[entity.LevelIds.Count - 1]);
                    if (firstLevel == null || lastLevel == null)
                        continue;

                    var firstPoint = UnregisteredPlanPoint(
                        firstLevel, entity.Geometry.Points[0]);
                    var lastPoint = UnregisteredPlanPoint(
                        lastLevel, entity.Geometry.Points[entity.Geometry.Points.Count - 1]);
                    var firstKnown = result.TryGetValue(firstLevel.Id, out var firstOffset);
                    var lastKnown = result.TryGetValue(lastLevel.Id, out var lastOffset);
                    if (firstKnown && !lastKnown)
                    {
                        result[lastLevel.Id] = firstPoint + firstOffset - lastPoint;
                        changed = true;
                    }
                    else if (!firstKnown && lastKnown)
                    {
                        result[firstLevel.Id] = lastPoint + lastOffset - firstPoint;
                        changed = true;
                    }
                }

                if (!changed)
                    break;
            }

            foreach (var level in levels)
            {
                if (!result.ContainsKey(level.Id))
                    result[level.Id] = Vector2.zero;
            }
            return result;
        }

        private static ReplayLevel FindLevel(
            IReadOnlyList<ReplayLevel> levels,
            string levelId)
        {
            foreach (var level in levels)
            {
                if (string.Equals(level.Id, levelId, StringComparison.Ordinal))
                    return level;
            }
            return null;
        }

        private static Vector2 UnregisteredPlanPoint(ReplayLevel level, Vector2 sourcePoint)
        {
            return new Vector2(
                sourcePoint.x - level.SourceOrigin.x,
                -(sourcePoint.y - level.SourceOrigin.y));
        }
    }

    public readonly struct PassengerPose
    {
        public int Id { get; }
        public Vector3 Position { get; }
        public Vector3 Forward { get; }
        public string LevelId { get; }
        public string State { get; }
        public string Intent { get; }
        public bool InVerticalFacility { get; }

        public PassengerPose(
            int id,
            Vector3 position,
            Vector3 forward,
            string levelId,
            string state,
            bool inVerticalFacility,
            string intent = "")
        {
            Id = id;
            Position = position;
            Forward = forward.sqrMagnitude < 0.001f ? Vector3.forward : forward.normalized;
            LevelId = levelId;
            State = state;
            Intent = intent ?? string.Empty;
            InVerticalFacility = inVerticalFacility;
        }
    }

    public readonly struct VerticalFacilityRoute
    {
        public Vector3 HighAnchor { get; }
        public Vector3 LowAnchor { get; }
        public Vector3 Middle { get; }

        public VerticalFacilityRoute(Vector3 highAnchor, Vector3 lowAnchor, Vector3 middle)
        {
            HighAnchor = highAnchor;
            LowAnchor = lowAnchor;
            Middle = middle;
        }

        public Vector3 Sample(Vector3 serviceStart, float progress)
        {
            progress = Mathf.Clamp01(progress);
            var startsHigh = Mathf.Abs(serviceStart.y - HighAnchor.y)
                <= Mathf.Abs(serviceStart.y - LowAnchor.y);
            return startsHigh
                ? SamplePolyline(HighAnchor, Middle, LowAnchor, progress)
                : SamplePolyline(LowAnchor, Middle, HighAnchor, progress);
        }

        private static Vector3 SamplePolyline(
            Vector3 first,
            Vector3 middle,
            Vector3 last,
            float progress)
        {
            var firstLength = Vector3.Distance(first, middle);
            var secondLength = Vector3.Distance(middle, last);
            var total = firstLength + secondLength;
            if (total < 0.001f)
                return last;

            var distance = progress * total;
            if (distance <= firstLength && firstLength > 0.001f)
                return Vector3.LerpUnclamped(first, middle, distance / firstLength);
            if (secondLength < 0.001f)
                return last;
            return Vector3.LerpUnclamped(
                middle, last, (distance - firstLength) / secondLength);
        }
    }

    public static class VerticalFacilityRouteResolver
    {
        private const float EscalatorAngleDegrees = 30f;
        private const float StairAngleDegrees = 35f;

        public static VerticalFacilityRoute Resolve(
            string kind,
            Vector3 firstAnchor,
            Vector3 secondAnchor)
        {
            var high = firstAnchor.y >= secondAnchor.y ? firstAnchor : secondAnchor;
            var low = firstAnchor.y >= secondAnchor.y ? secondAnchor : firstAnchor;
            var flat = high - low;
            flat.y = 0f;
            var rise = Mathf.Abs(high.y - low.y);
            var angle = string.Equals(kind, "stairs", StringComparison.OrdinalIgnoreCase)
                ? StairAngleDegrees
                : EscalatorAngleDegrees;
            var minimumRun = rise / Mathf.Tan(angle * Mathf.Deg2Rad);
            if (flat.magnitude >= minimumRun - 0.001f)
                return new VerticalFacilityRoute(high, low, Vector3.Lerp(low, high, 0.5f));

            // Keep one legible main flight.  The high-level authoritative anchor is
            // retained as the first route point and joins the generated incline across
            // the upper concourse floor, while the visible incline stays out of the
            // track envelope.
            var direction = flat.sqrMagnitude > 0.001f
                ? flat.normalized
                : Vector3.forward;
            var middle = low + direction * minimumRun;
            middle.y = high.y;
            return new VerticalFacilityRoute(high, low, middle);
        }
    }
}
