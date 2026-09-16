package com.divine.client.mixin;

import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;
import com.divine.client.DivineClient;
import com.divine.client.features.render.RenderFeatures;

@Mixin(targets = {"net.minecraft.client.render.GameRenderer", "net.minecraft.class_757"})
public class GameRendererMixin {

    @Inject(method = {"getFov", "method_3197"}, at = @At("RETURN"), cancellable = true, remap = false)
    private void onGetFov(Object camera, float tickDelta, boolean changingFov, CallbackInfoReturnable<Double> cir) {
        try {
            if (RenderFeatures.isZooming && DivineClient.CONFIG != null && DivineClient.CONFIG.zoom_enabled) {
                double original = cir.getReturnValue();
                cir.setReturnValue(original * RenderFeatures.getFovModifier(DivineClient.CONFIG));
            }
        } catch (Throwable ignored) {}
    }
}
