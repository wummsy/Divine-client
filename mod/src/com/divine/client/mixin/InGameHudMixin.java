package com.divine.client.mixin;

import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import com.divine.client.DivineClient;
import com.divine.client.features.hud.DivineHudRenderer;
import com.divine.client.gui.DivineCosmeticsScreen;
import com.divine.client.gui.DivineModMenuScreen;

@Mixin(targets = {"net.minecraft.client.gui.hud.InGameHud", "net.minecraft.class_329"})
public class InGameHudMixin {

    @Inject(method = {"render", "method_1753"}, at = @At("TAIL"), remap = false)
    private void onRenderHud(Object drawContext, float tickDelta, CallbackInfo ci) {
        try {
            DivineHudRenderer.renderHud(drawContext, DivineClient.minecraftInstance, tickDelta, DivineClient.CONFIG);
            if (DivineModMenuScreen.isOpen) {
                DivineModMenuScreen.render(drawContext, DivineClient.minecraftInstance, 854, 480, 0, 0, DivineClient.CONFIG);
            } else if (DivineCosmeticsScreen.isOpen) {
                DivineCosmeticsScreen.render(drawContext, DivineClient.minecraftInstance, 854, 480, 0, 0, DivineClient.CONFIG);
            }
        } catch (Throwable ignored) {}
    }
}
