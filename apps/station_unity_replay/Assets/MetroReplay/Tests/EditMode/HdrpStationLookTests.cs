using System.Collections;
using System.Linq;
using MetroReplay.Presentation;
using NUnit.Framework;
using UnityEngine;

namespace MetroReplay.Tests
{
    public sealed class HdrpStationLookTests
    {
        [Test]
        public void EnablesContactShadowsOnHdrpLight()
        {
            var lightObject = new GameObject("ContactShadowLightTest");
            try
            {
                var light = lightObject.AddComponent<Light>();
                InvokeLook("EnsureAdditionalLightData", light);

                var additional = lightObject.GetComponents<Component>()
                    .SingleOrDefault(component =>
                        component.GetType().Name == "HDAdditionalLightData");
                Assert.That(additional, Is.Not.Null);
                var setting = additional.GetType().GetProperty("useContactShadow")
                    ?.GetValue(additional);
                Assert.That(setting, Is.Not.Null);
                Assert.That(
                    setting.GetType().GetProperty("useOverride")?.GetValue(setting),
                    Is.True);
                Assert.That(
                    setting.GetType().GetProperty("override")?.GetValue(setting),
                    Is.True);
            }
            finally
            {
                Object.DestroyImmediate(lightObject);
            }
        }

        [Test]
        public void RuntimeVolumeEnablesContactShadowPass()
        {
            var root = new GameObject("ContactShadowVolumeTest");
            try
            {
                InvokeLook(
                    "Build",
                    root.transform,
                    new Bounds(Vector3.zero, Vector3.one * 12f));

                var volume = root.GetComponentsInChildren<Component>()
                    .SingleOrDefault(component => component.GetType().Name == "Volume");
                Assert.That(volume, Is.Not.Null);
                var profile = volume.GetType().GetField("sharedProfile")
                    ?.GetValue(volume)
                    ?? volume.GetType().GetProperty("profile")?.GetValue(volume);
                Assert.That(profile, Is.Not.Null);
                var components = profile.GetType().GetField("components")
                    ?.GetValue(profile) as IEnumerable;
                Assert.That(components, Is.Not.Null);
                var contactShadows = components.Cast<object>().SingleOrDefault(
                    component => component.GetType().Name == "ContactShadows");
                Assert.That(contactShadows, Is.Not.Null);
                Assert.That(ReadParameterValue<bool>(contactShadows, "enable"), Is.True);
                Assert.That(ReadParameterValue<float>(contactShadows, "opacity"),
                    Is.GreaterThan(0.8f));
            }
            finally
            {
                Object.DestroyImmediate(root);
            }
        }

        private static T ReadParameterValue<T>(object component, string fieldName)
        {
            var parameter = component.GetType().GetField(fieldName)?.GetValue(component);
            Assert.That(parameter, Is.Not.Null);
            return (T)parameter.GetType().GetProperty("value").GetValue(parameter);
        }

        private static void InvokeLook(string methodName, params object[] arguments)
        {
            var lookType = typeof(PassengerPool).Assembly.GetType(
                "MetroReplay.Presentation.HdrpStationLook");
            Assert.That(lookType, Is.Not.Null);
            var method = lookType.GetMethod(methodName);
            Assert.That(method, Is.Not.Null);
            method.Invoke(null, arguments);
        }
    }
}
