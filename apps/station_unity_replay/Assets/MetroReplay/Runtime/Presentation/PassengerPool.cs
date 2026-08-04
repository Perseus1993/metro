using System;
using System.Collections.Generic;
using MetroReplay.Domain;
using UnityEngine;

namespace MetroReplay.Presentation
{
    public sealed class PassengerPool
    {
        private sealed class Slot
        {
            public GameObject GameObject;
            public Renderer Renderer;
            public Renderer[] AvatarRenderers;
            public Animation Animation;
            public Animator Animator;
            public string AnimationName;
            public int PassengerId = -1;
            public int AppearanceId = -1;
            public int BaseIndex = -1;
            public float VisualGroundOffset;
        }

        private readonly Transform _parent;
        private readonly List<Slot> _slots = new List<Slot>();
        private readonly Dictionary<int, Slot> _active = new Dictionary<int, Slot>();
        private readonly HashSet<int> _seen = new HashSet<int>();
        private readonly List<int> _retire = new List<int>();
        private readonly List<GameObject> _prototypes = new List<GameObject>();
        private readonly Material _capsuleMaterial;
        private readonly MaterialPropertyBlock _propertyBlock = new MaterialPropertyBlock();
        private readonly int _preferredCapacity;
        private PassengerSkinAtlas _skinAtlas;

        public int ActiveCount => _active.Count;
        public int Capacity => _slots.Count;
        public int BaseModelCount => _prototypes.Count;
        public bool UsesThreeDimensionalAvatar => _prototypes.Count > 0;

        public PassengerPool(Transform parent, int initialCapacity)
        {
            _parent = parent;
            _preferredCapacity = initialCapacity;
            _capsuleMaterial = ReplayMaterialFactory.Create("MetroReplay_Passenger", Color.white);
            Warm(initialCapacity);
        }

        public void UsePrototype(GameObject prototype)
        {
            if (prototype == null)
                throw new ArgumentNullException(nameof(prototype));
            UsePrototypes(new[] { prototype });
        }

        public void UsePrototypes(IReadOnlyList<GameObject> prototypes)
        {
            if (prototypes == null || prototypes.Count == 0)
                throw new ArgumentException("At least one passenger prototype is required.", nameof(prototypes));
            ResetSlots();
            foreach (var prototype in prototypes)
            {
                if (prototype == null)
                    throw new ArgumentException("Passenger prototypes cannot contain null.", nameof(prototypes));
                _prototypes.Add(prototype);
            }
            Warm(_preferredCapacity);
        }

        public void UseSkinAtlas(PassengerSkinAtlas skinAtlas)
        {
            _skinAtlas = skinAtlas ?? throw new ArgumentNullException(nameof(skinAtlas));
            foreach (var slot in _slots)
            {
                slot.AppearanceId = -1;
                if (slot.PassengerId >= 0)
                    ApplyAppearance(slot, slot.PassengerId);
            }
        }

        public void Warm(int capacity)
        {
            while (_slots.Count < capacity)
                _slots.Add(CreateSlot(_slots.Count, SuggestedBaseIndex(_slots.Count)));
        }

        public void Sync(IReadOnlyList<PassengerPose> poses)
        {
            _seen.Clear();
            foreach (var pose in poses)
            {
                _seen.Add(pose.Id);
                if (!_active.TryGetValue(pose.Id, out var slot))
                {
                    slot = Acquire(pose.Id);
                    _active[pose.Id] = slot;
                }
                slot.GameObject.transform.SetPositionAndRotation(
                    pose.Position + Vector3.up * slot.VisualGroundOffset,
                    Quaternion.LookRotation(pose.Forward, Vector3.up));
                PassengerAnimationPlayer.Play(slot.Animator, slot.Animation, ref slot.AnimationName,
                    SelectAnimation(pose), pose.Id);
                ApplyCapsuleColor(slot, pose);
            }
            RetireMissing();
        }

        private Slot Acquire(int passengerId)
        {
            var requestedBase = _prototypes.Count == 0
                ? -1
                : PassengerAppearancePalette.GetBaseIndex(passengerId, _prototypes.Count);
            foreach (var slot in _slots)
            {
                if (slot.PassengerId >= 0 || slot.BaseIndex != requestedBase)
                    continue;
                Activate(slot, passengerId);
                return slot;
            }
            var created = CreateSlot(_slots.Count, requestedBase);
            _slots.Add(created);
            Activate(created, passengerId);
            return created;
        }

        private void Activate(Slot slot, int passengerId)
        {
            slot.PassengerId = passengerId;
            slot.GameObject.SetActive(true);
            ApplyAppearance(slot, passengerId);
        }

        private Slot CreateSlot(int index, int baseIndex)
        {
            if (_prototypes.Count == 0)
                return CreateCapsule(index);
            var avatar = UnityEngine.Object.Instantiate(_prototypes[baseIndex], _parent, false);
            avatar.name = $"PassengerAvatarPool_{index:000}_{baseIndex:00}";
            avatar.SetActive(false);
            var animation = avatar.GetComponentInChildren<Animation>(true);
            var renderers = avatar.GetComponentsInChildren<Renderer>(true);
            var visualGroundOffset = CalculateVisualGroundOffset(avatar, renderers);
            PassengerAnimationPlayer.Configure(animation);
            return new Slot
            {
                GameObject = avatar,
                AvatarRenderers = renderers,
                Animation = animation,
                Animator = avatar.GetComponentInChildren<Animator>(true),
                BaseIndex = baseIndex,
                VisualGroundOffset = visualGroundOffset
            };
        }

        private Slot CreateCapsule(int index)
        {
            var passenger = GameObject.CreatePrimitive(PrimitiveType.Capsule);
            passenger.name = $"PassengerPool_{index:000}";
            passenger.transform.SetParent(_parent, false);
            passenger.transform.localScale = new Vector3(0.42f, 0.85f, 0.42f);
            var collider = passenger.GetComponent<Collider>();
            if (collider != null)
                DestroyObject(collider);
            var renderer = passenger.GetComponent<Renderer>();
            renderer.sharedMaterial = _capsuleMaterial;
            passenger.SetActive(false);
            return new Slot
            {
                GameObject = passenger,
                Renderer = renderer,
                VisualGroundOffset = 0.85f
            };
        }

        private static float CalculateVisualGroundOffset(
            GameObject avatar,
            IReadOnlyList<Renderer> renderers)
        {
            var minimumY = float.PositiveInfinity;
            foreach (var renderer in renderers)
            {
                if (renderer != null)
                    minimumY = Mathf.Min(minimumY, renderer.bounds.min.y);
            }
            if (float.IsInfinity(minimumY) || float.IsNaN(minimumY))
                return 0f;
            return avatar.transform.position.y - minimumY;
        }

        private void ApplyAppearance(Slot slot, int passengerId)
        {
            if (slot.AppearanceId == passengerId)
                return;
            if (_prototypes.Count > 1)
                PassengerAppearanceApplicator.Apply(slot.AvatarRenderers, passengerId, _propertyBlock);
            else if (_skinAtlas != null)
                _skinAtlas.Apply(slot.AvatarRenderers, passengerId, _propertyBlock);
            slot.AppearanceId = passengerId;
        }

        private void ApplyCapsuleColor(Slot slot, PassengerPose pose)
        {
            if (slot.Renderer == null)
                return;
            var color = pose.InVerticalFacility
                ? new Color(1f, 0.61f, 0.15f)
                : Color.HSVToRGB(Mathf.Repeat(pose.Id * 0.61803398875f, 1f), 0.58f, 0.95f);
            _propertyBlock.Clear();
            _propertyBlock.SetColor("_BaseColor", color);
            _propertyBlock.SetColor("_Color", color);
            slot.Renderer.SetPropertyBlock(_propertyBlock);
        }

        private void RetireMissing()
        {
            _retire.Clear();
            foreach (var pair in _active)
                if (!_seen.Contains(pair.Key))
                    _retire.Add(pair.Key);
            foreach (var passengerId in _retire)
            {
                var slot = _active[passengerId];
                slot.PassengerId = -1;
                slot.AppearanceId = -1;
                slot.AnimationName = null;
                slot.Animation?.Stop();
                slot.GameObject.SetActive(false);
                _active.Remove(passengerId);
            }
        }

        private void ResetSlots()
        {
            foreach (var slot in _slots)
                DestroyObject(slot.GameObject);
            _slots.Clear();
            _active.Clear();
            _prototypes.Clear();
        }

        private int SuggestedBaseIndex(int slotIndex) =>
            _prototypes.Count == 0 ? -1 : slotIndex % _prototypes.Count;

        private static void DestroyObject(UnityEngine.Object target)
        {
            if (UnityEngine.Application.isPlaying)
                UnityEngine.Object.Destroy(target);
            else
                UnityEngine.Object.DestroyImmediate(target);
        }

        public static string SelectAnimation(PassengerPose pose)
        {
            var state = pose.State ?? string.Empty;
            if (ContainsAny(state, "queue", "wait", "away", "closed", "open"))
                return "Idle_Loop";
            if (ContainsAny(state, "run"))
                return "Jog_Fwd_Loop";
            if (!pose.InVerticalFacility
                && ContainsAny(pose.Intent ?? string.Empty, "evacuate", "emergency", "clearance")
                && ContainsAny(state, "walk", "moving", "approach"))
                return "Jog_Fwd_Loop";
            if (pose.InVerticalFacility || ContainsAny(state, "walk", "riding"))
                return "Walk_Loop";
            return "Idle_Loop";
        }

        private static bool ContainsAny(string value, params string[] terms)
        {
            foreach (var term in terms)
                if (value.IndexOf(term, StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
            return false;
        }
    }
}
