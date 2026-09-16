package org.spongepowered.asm.mixin.injection;

import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;

@Retention(RetentionPolicy.CLASS)
public @interface At {
    String value();
    String target() default "";
    int shift() default 0;
    int by() default 0;
    int ordinal() default -1;
    String slice() default "";
}
