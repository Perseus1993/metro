using MetroReplay.Presentation;
using NUnit.Framework;

namespace MetroReplay.Tests
{
    public sealed class PassengerAppearancePaletteTests
    {
        [Test]
        public void BaseSelectionIsDeterministicAndInRange()
        {
            for (var passengerId = 0; passengerId < 1000; passengerId++)
            {
                var first = PassengerAppearancePalette.GetBaseIndex(passengerId, 8);
                var second = PassengerAppearancePalette.GetBaseIndex(passengerId, 8);
                Assert.That(first, Is.EqualTo(second));
                Assert.That(first, Is.InRange(0, 7));
            }
        }

        [Test]
        public void PaletteExposesRequiredVariation()
        {
            Assert.That(PassengerAppearancePalette.ClothingVariantCount, Is.GreaterThanOrEqualTo(6));
            Assert.That(PassengerAppearancePalette.SkinVariantCount, Is.GreaterThanOrEqualTo(4));
        }
    }
}
