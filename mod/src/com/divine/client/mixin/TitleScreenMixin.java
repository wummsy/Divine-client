package com.divine.client.mixin;

import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;
import com.divine.client.DivineClient;
import com.divine.client.gui.DivineCosmeticsScreen;
import com.divine.client.gui.DivineModMenuScreen;
import com.divine.client.gui.DivineTitleScreen;

@Mixin(targets = {"net.minecraft.client.gui.screen.TitleScreen", "net.minecraft.class_442"})
public class TitleScreenMixin {

    @Inject(method = {"init", "method_25426"}, at = @At("HEAD"), remap = false)
    private void onInit(CallbackInfo ci) {
        try {
            DivineTitleScreen.onScreenInit(DivineClient.minecraftInstance, this, 854, 480);
        } catch (Throwable ignored) {}
    }

    @Inject(method = {"init", "method_25426"}, at = @At("TAIL"), remap = false)
    private void onInitTail(CallbackInfo ci) {
        try {
            DivineTitleScreen.clearVanillaWidgets(this);
        } catch (Throwable ignored) {}
    }

    @Inject(method = {"render", "method_25394"}, at = @At("HEAD"), cancellable = true, remap = false)
    private void onRender(Object drawContext, int mouseX, int mouseY, float delta, CallbackInfo ci) {
        try {
            DivineTitleScreen.renderCustomMenu(drawContext, DivineClient.minecraftInstance, this, mouseX, mouseY, delta, DivineClient.CONFIG);
            if (DivineModMenuScreen.isOpen) {
                DivineModMenuScreen.render(drawContext, DivineClient.minecraftInstance, 854, 480, mouseX, mouseY, DivineClient.CONFIG);
            } else if (DivineCosmeticsScreen.isOpen) {
                DivineCosmeticsScreen.render(drawContext, DivineClient.minecraftInstance, 854, 480, mouseX, mouseY, DivineClient.CONFIG);
            }
            ci.cancel();
        } catch (Throwable ignored) {}
    }

    @Inject(method = {"mouseClicked", "method_25402"}, at = @At("HEAD"), cancellable = true, remap = false)
    private void onMouseClicked(double mouseX, double mouseY, int button, CallbackInfoReturnable<Boolean> cir) {
        try {
            if (DivineModMenuScreen.isOpen) {
                if (DivineModMenuScreen.handleClick(mouseX, mouseY, button, 854, 480, DivineClient.CONFIG)) {
                    cir.setReturnValue(true);
                    return;
                }
            } else if (DivineCosmeticsScreen.isOpen) {
                if (DivineCosmeticsScreen.handleClick(mouseX, mouseY, button, 854, 480, DivineClient.CONFIG)) {
                    cir.setReturnValue(true);
                    return;
                }
            } else {
                if (DivineTitleScreen.handleMouseClick(DivineClient.minecraftInstance, this, mouseX, mouseY, button, DivineClient.CONFIG)) {
                    cir.setReturnValue(true);
                    return;
                }
            }
        } catch (Throwable ignored) {}
    }
}
