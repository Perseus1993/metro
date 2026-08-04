using System;
using System.Collections.Generic;
using System.Globalization;
using MetroReplay.Domain;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace MetroReplay.Infrastructure
{
    public sealed class ReplayContractException : Exception
    {
        public ReplayContractException(string message) : base(message)
        {
        }

        public ReplayContractException(string message, Exception innerException) : base(message, innerException)
        {
        }
    }

    public static class ReplayContractReader
    {
        public static ReplayData Read(string json)
        {
            if (string.IsNullOrWhiteSpace(json))
                throw new ReplayContractException("Replay JSON is empty.");

            JObject root;
            try
            {
                root = JObject.Parse(json);
            }
            catch (JsonException exception)
            {
                throw new ReplayContractException("Replay JSON is malformed.", exception);
            }

            RequireVersion(root, "visualization_bundle.v1", "root");
            var package = RequireObject(root, "replay_package", "root");
            RequireVersion(package, "replay_package.v2", "replay_package");
            var scene = RequireObject(package, "station_scene", "replay_package");
            RequireVersion(scene, "station_scene.v1", "station_scene");
            var trace = RequireObject(root, "simulation_trace", "root");
            RequireVersion(trace, "simulation_trace.v1", "simulation_trace");

            var levels = ReadLevels(RequireArray(scene, "levels", "station_scene"));
            if (levels.Count < 2)
                throw new ReplayContractException("station_scene.levels must contain at least two levels for 3D replay.");

            var levelIds = new HashSet<string>(StringComparer.Ordinal);
            foreach (var level in levels)
            {
                if (!levelIds.Add(level.Id))
                    throw new ReplayContractException($"Duplicate level_id '{level.Id}'.");
            }

            var entities = ReadEntities(RequireArray(scene, "entities", "station_scene"), levelIds);
            ValidateRuntimeBindings(scene["runtime_bindings"] as JArray, entities);
            var frames = ReadFrames(RequireArray(trace, "snapshots", "simulation_trace"), levelIds);
            var serviceEvents = ReadFacilityEvents(trace["facility_events"] as JArray, levelIds);
            var clearanceAudit = ReadClearanceAudit(root["clearance_audit"] as JObject);
            var fidelity = ReadFidelity(trace);
            ValidateClearanceFrames(clearanceAudit, frames);

            var runId = OptionalString(root, "source_run_id", OptionalString(trace, "run_id", "unknown"));
            return new ReplayData(
                runId,
                levels,
                entities,
                frames,
                serviceEvents,
                clearanceAudit,
                fidelity);
        }

        private static ReplayFidelity ReadFidelity(JObject trace)
        {
            if (!(trace["metadata"] is JObject metadata)
                || !(metadata["replay_fidelity"] is JObject fidelity))
            {
                return ReplayFidelity.Unspecified;
            }

            var positionAuthority = OptionalString(fidelity, "position_authority", string.Empty);
            var snapshotInterval = OptionalFloat(fidelity, "snapshot_interval_seconds", 0f);
            var facilityAuthority = OptionalString(
                fidelity,
                "facility_motion_authority",
                string.Empty);
            var visualTracksAuthoritative = OptionalBool(
                fidelity,
                "visual_tracks_authoritative",
                false);
            var pluginIds = new List<string>();
            var decisionCount = 0;
            if (metadata["routing_evidence"] is JObject routing)
            {
                decisionCount = Mathf.Max(0, OptionalInt(routing, "decision_count", 0));
                if (routing["plugin_ids"] is JArray pluginTokens)
                {
                    foreach (var token in pluginTokens)
                    {
                        if (token.Type == JTokenType.String
                            && !string.IsNullOrWhiteSpace(token.Value<string>()))
                        {
                            pluginIds.Add(token.Value<string>());
                        }
                    }
                }
            }

            return new ReplayFidelity(
                positionAuthority,
                snapshotInterval,
                facilityAuthority,
                visualTracksAuthoritative,
                pluginIds,
                decisionCount);
        }

        private static ReplayClearanceAudit ReadClearanceAudit(JObject item)
        {
            if (item == null)
                return ReplayClearanceAudit.Unavailable;

            var clearedToken = item["cleared"];
            if (clearedToken?.Type != JTokenType.Boolean)
                throw new ReplayContractException("clearance_audit.cleared must be a boolean.");

            var totalPassengers = RequireInt(item, "total_agents", "clearance_audit");
            var completedPassengers = RequireInt(item, "completed_agents", "clearance_audit");
            var remainingPassengers = RequireInt(item, "remaining_agents", "clearance_audit");
            if (totalPassengers < 0 || completedPassengers < 0 || remainingPassengers < 0)
                throw new ReplayContractException("clearance_audit passenger counts cannot be negative.");
            if (completedPassengers + remainingPassengers > totalPassengers)
                throw new ReplayContractException(
                    "clearance_audit completed and remaining passengers exceed total_agents.");

            var cleared = clearedToken.Value<bool>();
            var clearanceTimeToken = item["clearance_time_s"];
            float? clearanceTime = null;
            if (clearanceTimeToken != null && clearanceTimeToken.Type != JTokenType.Null)
                clearanceTime = TokenFloat(clearanceTimeToken, "clearance_audit.clearance_time_s");

            if (cleared && (remainingPassengers != 0 || completedPassengers != totalPassengers))
                throw new ReplayContractException(
                    "A cleared replay must complete every passenger and have zero remaining passengers.");
            if (cleared && !clearanceTime.HasValue)
                throw new ReplayContractException(
                    "A cleared replay must provide clearance_audit.clearance_time_s.");

            return new ReplayClearanceAudit(
                true,
                cleared,
                OptionalString(item, "outcome", cleared ? "cleared" : "incomplete"),
                totalPassengers,
                completedPassengers,
                remainingPassengers,
                clearanceTime);
        }

        private static void ValidateClearanceFrames(
            ReplayClearanceAudit clearanceAudit,
            IReadOnlyList<ReplayFrame> frames)
        {
            if (!clearanceAudit.Cleared || frames.Count == 0)
                return;

            var finalVisiblePassengers = 0;
            foreach (var passenger in frames[frames.Count - 1].Passengers.Values)
                finalVisiblePassengers += passenger.Persons;
            if (finalVisiblePassengers != 0)
                throw new ReplayContractException(
                    "A cleared replay must contain zero passengers in its final snapshot.");
        }

        private static List<ReplayLevel> ReadLevels(JArray tokens)
        {
            var result = new List<ReplayLevel>(tokens.Count);
            for (var i = 0; i < tokens.Count; i++)
            {
                var item = RequireObject(tokens[i], $"station_scene.levels[{i}]");
                var id = RequireString(item, "level_id", $"station_scene.levels[{i}]");
                var label = OptionalString(item, "label", id);
                var elevation = RequireFloat(item, "elevation", $"station_scene.levels[{i}]");
                var footprint = ReadPoints(RequireArray(item, "footprint", $"station_scene.levels[{i}]"), $"level '{id}' footprint");
                if (footprint.Count < 3)
                    throw new ReplayContractException($"Level '{id}' footprint needs at least three points.");
                result.Add(new ReplayLevel(id, label, elevation, footprint));
            }
            return result;
        }

        private static List<ReplayEntity> ReadEntities(JArray tokens, HashSet<string> levelIds)
        {
            var result = new List<ReplayEntity>(tokens.Count);
            var entityIds = new HashSet<string>(StringComparer.Ordinal);
            for (var i = 0; i < tokens.Count; i++)
            {
                var path = $"station_scene.entities[{i}]";
                var item = RequireObject(tokens[i], path);
                var id = RequireString(item, "entity_id", path);
                if (!entityIds.Add(id))
                    throw new ReplayContractException($"Duplicate entity_id '{id}'.");

                var kind = RequireString(item, "kind", path);
                var label = OptionalString(item, "label", id);
                var geometryToken = RequireObject(item, "geometry", path);
                var points = geometryToken["points_m"] is JArray pointsArray
                    ? ReadPoints(pointsArray, $"entity '{id}' geometry")
                    : new List<Vector2>();
                var geometry = new ReplayGeometry(
                    OptionalString(geometryToken, "shape", "point"),
                    OptionalFloat(geometryToken, "x_m", 0f),
                    OptionalFloat(geometryToken, "y_m", 0f),
                    OptionalFloat(geometryToken, "width_m", 0f),
                    OptionalFloat(geometryToken, "height_m", 0f),
                    OptionalFloat(geometryToken, "rotation_deg", 0f),
                    points);

                var entityLevels = ReadStringArray(RequireArray(item, "level_ids", path), $"entity '{id}' level_ids");
                if (entityLevels.Count == 0)
                    throw new ReplayContractException($"Entity '{id}' does not reference a level.");
                foreach (var levelId in entityLevels)
                {
                    if (!levelIds.Contains(levelId))
                        throw new ReplayContractException($"Entity '{id}' references unknown level '{levelId}'.");
                }

                result.Add(new ReplayEntity(id, kind, label, geometry, entityLevels));
            }
            return result;
        }

        private static void ValidateRuntimeBindings(JArray tokens, IReadOnlyList<ReplayEntity> entities)
        {
            if (tokens == null)
                return;

            var entityIds = new HashSet<string>(StringComparer.Ordinal);
            foreach (var entity in entities)
                entityIds.Add(entity.Id);

            for (var i = 0; i < tokens.Count; i++)
            {
                var binding = RequireObject(tokens[i], $"station_scene.runtime_bindings[{i}]");
                var entityId = RequireString(binding, "scene_entity_id", $"station_scene.runtime_bindings[{i}]");
                if (!entityIds.Contains(entityId))
                    throw new ReplayContractException($"Runtime binding references unknown scene entity '{entityId}'.");
            }
        }

        private static List<ReplayFrame> ReadFrames(JArray tokens, HashSet<string> levelIds)
        {
            var byTime = new SortedDictionary<float, ReplayFrame>();
            for (var i = 0; i < tokens.Count; i++)
            {
                var path = $"simulation_trace.snapshots[{i}]";
                var item = RequireObject(tokens[i], path);
                var time = RequireFloat(item, "time_seconds", path);
                if (time < 0f)
                    throw new ReplayContractException($"{path}.time_seconds cannot be negative.");

                var passengers = new Dictionary<int, PassengerSnapshot>();
                if (item["passengers"] is JArray passengerTokens)
                {
                    for (var passengerIndex = 0; passengerIndex < passengerTokens.Count; passengerIndex++)
                    {
                        var passengerPath = $"{path}.passengers[{passengerIndex}]";
                        var passenger = RequireObject(passengerTokens[passengerIndex], passengerPath);
                        var id = RequireInt(passenger, "id", passengerPath);
                        var levelId = RequireString(passenger, "current_level_id", passengerPath);
                        if (!levelIds.Contains(levelId))
                            throw new ReplayContractException($"Passenger {id} references unknown level '{levelId}'.");
                        if (passengers.ContainsKey(id))
                            throw new ReplayContractException($"Frame {time.ToString(CultureInfo.InvariantCulture)} contains duplicate passenger {id}.");

                        passengers[id] = new PassengerSnapshot(
                            id,
                            RequireFloat(passenger, "x", passengerPath),
                            RequireFloat(passenger, "y", passengerPath),
                            levelId,
                            OptionalString(passenger, "state", string.Empty),
                            OptionalString(passenger, "intent", string.Empty),
                            Mathf.Max(1, OptionalInt(passenger, "n", 1)));
                    }
                }

                var trains = new Dictionary<int, TrainSnapshot>();
                if (item["trains"] is JArray trainTokens)
                {
                    for (var trainIndex = 0; trainIndex < trainTokens.Count; trainIndex++)
                    {
                        var trainPath = $"{path}.trains[{trainIndex}]";
                        var train = RequireObject(trainTokens[trainIndex], trainPath);
                        var id = RequireInt(train, "id", trainPath);
                        if (trains.ContainsKey(id))
                            throw new ReplayContractException($"Frame {time.ToString(CultureInfo.InvariantCulture)} contains duplicate train {id}.");

                        var departureElapsed = OptionalNullableFloat(
                            train,
                            "departure_elapsed_seconds",
                            trainPath);
                        var nextArrival = RequireFloat(train, "next_arrival_seconds", trainPath);
                        if (departureElapsed < 0f || nextArrival < 0f)
                            throw new ReplayContractException($"{trainPath} train times cannot be negative.");

                        trains[id] = new TrainSnapshot(
                            id,
                            RequireString(train, "line_id", trainPath),
                            RequireString(train, "direction", trainPath),
                            RequireString(train, "platform_id", trainPath),
                            RequireString(train, "state", trainPath),
                            RequireNonNegativeInt(train, "current_load_persons", trainPath),
                            RequireNonNegativeInt(train, "last_departed_load_persons", trainPath),
                            departureElapsed,
                            RequireNonNegativeInt(train, "departed_trains", trainPath),
                            RequireNonNegativeInt(train, "cancelled_trains", trainPath),
                            nextArrival,
                            OptionalBool(train, "service_suspended", false),
                            RequireNonNegativeInt(train, "capacity_persons", trainPath));
                    }
                }

                // The simulator may emit two evidence snapshots at the same clock time.
                // The latest one is authoritative and makes random seeking deterministic.
                byTime[time] = new ReplayFrame(time, passengers, trains);
            }

            var result = new List<ReplayFrame>(byTime.Count);
            foreach (var pair in byTime)
                result.Add(pair.Value);
            return result;
        }

        private static List<FacilityServiceEvent> ReadFacilityEvents(JArray tokens, HashSet<string> levelIds)
        {
            var result = new List<FacilityServiceEvent>(tokens?.Count ?? 0);
            if (tokens == null)
                return result;

            for (var i = 0; i < tokens.Count; i++)
            {
                var path = $"simulation_trace.facility_events[{i}]";
                var item = RequireObject(tokens[i], path);
                var start = RequireFloat(item, "start_time", path);
                var end = RequireFloat(item, "end_time", path);
                if (end < start)
                    throw new ReplayContractException($"{path}.end_time precedes start_time.");

                var fromLevel = OptionalString(item, "from_level", string.Empty);
                var toLevel = OptionalString(item, "to_level", fromLevel);
                if (!string.IsNullOrEmpty(fromLevel) && !levelIds.Contains(fromLevel))
                    throw new ReplayContractException($"{path} references unknown from_level '{fromLevel}'.");
                if (!string.IsNullOrEmpty(toLevel) && !levelIds.Contains(toLevel))
                    throw new ReplayContractException($"{path} references unknown to_level '{toLevel}'.");

                result.Add(new FacilityServiceEvent(
                    RequireInt(item, "event_id", path),
                    RequireString(item, "facility_id", path),
                    RequireString(item, "facility_kind", path),
                    ReadIntArray(RequireArray(item, "passenger_ids", path), $"{path}.passenger_ids"),
                    start,
                    OptionalFloat(item, "board_end_time", start),
                    OptionalFloat(item, "arrive_time", end),
                    end,
                    ReadPoint(RequireArray(item, "start_position", path), $"{path}.start_position"),
                    ReadPoint(RequireArray(item, "end_position", path), $"{path}.end_position"),
                    fromLevel,
                    toLevel));
            }

            result.Sort((left, right) => left.StartTime.CompareTo(right.StartTime));
            return result;
        }

        private static List<Vector2> ReadPoints(JArray tokens, string path)
        {
            var result = new List<Vector2>(tokens.Count);
            for (var i = 0; i < tokens.Count; i++)
                result.Add(ReadPoint(RequireArray(tokens[i], $"{path}[{i}]"), $"{path}[{i}]"));
            return result;
        }

        private static Vector2 ReadPoint(JArray token, string path)
        {
            if (token.Count < 2)
                throw new ReplayContractException($"{path} must contain x and y.");
            return new Vector2(TokenFloat(token[0], $"{path}[0]"), TokenFloat(token[1], $"{path}[1]"));
        }

        private static List<string> ReadStringArray(JArray tokens, string path)
        {
            var result = new List<string>(tokens.Count);
            for (var i = 0; i < tokens.Count; i++)
            {
                var value = tokens[i].Type == JTokenType.String ? tokens[i].Value<string>() : null;
                if (string.IsNullOrWhiteSpace(value))
                    throw new ReplayContractException($"{path}[{i}] must be a non-empty string.");
                result.Add(value);
            }
            return result;
        }

        private static List<int> ReadIntArray(JArray tokens, string path)
        {
            var result = new List<int>(tokens.Count);
            for (var i = 0; i < tokens.Count; i++)
            {
                if (tokens[i].Type != JTokenType.Integer)
                    throw new ReplayContractException($"{path}[{i}] must be an integer.");
                result.Add(tokens[i].Value<int>());
            }
            return result;
        }

        private static void RequireVersion(JObject item, string expected, string path)
        {
            var actual = RequireString(item, "schema_version", path);
            if (!string.Equals(actual, expected, StringComparison.Ordinal))
                throw new ReplayContractException($"Unsupported {path}.schema_version '{actual}'; expected '{expected}'.");
        }

        private static JObject RequireObject(JObject item, string property, string path)
        {
            return RequireObject(item[property], $"{path}.{property}");
        }

        private static JObject RequireObject(JToken token, string path)
        {
            if (token is JObject result)
                return result;
            throw new ReplayContractException($"{path} must be an object.");
        }

        private static JArray RequireArray(JObject item, string property, string path)
        {
            return RequireArray(item[property], $"{path}.{property}");
        }

        private static JArray RequireArray(JToken token, string path)
        {
            if (token is JArray result)
                return result;
            throw new ReplayContractException($"{path} must be an array.");
        }

        private static string RequireString(JObject item, string property, string path)
        {
            var token = item[property];
            var result = token?.Type == JTokenType.String ? token.Value<string>() : null;
            if (string.IsNullOrWhiteSpace(result))
                throw new ReplayContractException($"{path}.{property} must be a non-empty string.");
            return result;
        }

        private static float RequireFloat(JObject item, string property, string path)
        {
            if (item[property] == null)
                throw new ReplayContractException($"{path}.{property} is required.");
            return TokenFloat(item[property], $"{path}.{property}");
        }

        private static int RequireInt(JObject item, string property, string path)
        {
            var token = item[property];
            if (token?.Type != JTokenType.Integer)
                throw new ReplayContractException($"{path}.{property} must be an integer.");
            return token.Value<int>();
        }

        private static int RequireNonNegativeInt(JObject item, string property, string path)
        {
            var value = RequireInt(item, property, path);
            if (value < 0)
                throw new ReplayContractException($"{path}.{property} cannot be negative.");
            return value;
        }

        private static string OptionalString(JObject item, string property, string fallback)
        {
            var token = item[property];
            return token?.Type == JTokenType.String ? token.Value<string>() ?? fallback : fallback;
        }

        private static float OptionalFloat(JObject item, string property, float fallback)
        {
            var token = item[property];
            if (token == null || token.Type == JTokenType.Null)
                return fallback;
            return TokenFloat(token, $"{property}");
        }

        private static int OptionalInt(JObject item, string property, int fallback)
        {
            var token = item[property];
            return token?.Type == JTokenType.Integer ? token.Value<int>() : fallback;
        }

        private static float? OptionalNullableFloat(JObject item, string property, string path)
        {
            var token = item[property];
            if (token == null || token.Type == JTokenType.Null)
                return null;
            return TokenFloat(token, $"{path}.{property}");
        }

        private static bool OptionalBool(JObject item, string property, bool fallback)
        {
            var token = item[property];
            return token?.Type == JTokenType.Boolean ? token.Value<bool>() : fallback;
        }

        private static float TokenFloat(JToken token, string path)
        {
            if (token.Type != JTokenType.Float && token.Type != JTokenType.Integer)
                throw new ReplayContractException($"{path} must be numeric.");
            var value = token.Value<double>();
            if (double.IsNaN(value) || double.IsInfinity(value))
                throw new ReplayContractException($"{path} must be finite.");
            return (float)value;
        }
    }
}
