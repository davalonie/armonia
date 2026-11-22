package com.armonia.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val DarkColorScheme = darkColorScheme(
    primary = ArmoniaAccent,
    onPrimary = ArmoniaBlack,
    primaryContainer = Color(0xFF4B2E00), // Darker orange for containers
    onPrimaryContainer = ArmoniaAccent,

    secondary = ArmoniaSurfaceContainerHigh,
    onSecondary = ArmoniaOnSurface,
    secondaryContainer = ArmoniaSurfaceVariant,
    onSecondaryContainer = ArmoniaOnSurface,

    background = ArmoniaBackground,
    onBackground = ArmoniaOnSurface,

    surface = ArmoniaSurface,
    onSurface = ArmoniaOnSurface,
    surfaceVariant = ArmoniaSurfaceVariant,
    onSurfaceVariant = ArmoniaOnSurface,

    surfaceContainer = ArmoniaSurfaceContainer,
    surfaceContainerLow = ArmoniaSurface,
    surfaceContainerHigh = ArmoniaSurfaceContainerHigh,
    surfaceContainerHighest = ArmoniaSurfaceContainerHighest,

    outline = ArmoniaOutline,
    outlineVariant = ArmoniaOutlineVariant,

    error = Color(0xFFFF5449),
    onError = ArmoniaBlack,
    errorContainer = Color(0xFF410E0B),
    onErrorContainer = Color(0xFFFFDAD6),
)

@Composable
fun ArmoniaTheme(
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = DarkColorScheme,
        typography = ArmoniaTypography,
        content = content,
    )
}
