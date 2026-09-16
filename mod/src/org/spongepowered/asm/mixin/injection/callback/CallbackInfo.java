package org.spongepowered.asm.mixin.injection.callback;

public class CallbackInfo {
    private boolean cancelled = false;

    public void cancel() {
        this.cancelled = true;
    }

    public boolean isCancelled() {
        return this.cancelled;
    }
}
