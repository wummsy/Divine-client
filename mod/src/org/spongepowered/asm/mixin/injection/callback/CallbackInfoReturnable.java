package org.spongepowered.asm.mixin.injection.callback;

public class CallbackInfoReturnable<R> extends CallbackInfo {
    private R returnValue;

    public void setReturnValue(R value) {
        this.returnValue = value;
        cancel();
    }

    public R getReturnValue() {
        return this.returnValue;
    }
}
