package com.armonia.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color

/** The «Tus favoritos» cover of Inicio, for the rows of Biblioteca and of the playlist sheet. The caller sizes and clips it. */
@Composable
fun FavoritesCover(modifier: Modifier = Modifier) {
    Box(modifier.background(Brush.linearGradient(listOf(Color(0xFF5B2DD6), Color(0xFFA78BFA), Color(0xFFC9F2E4)))),
        contentAlignment = Alignment.Center) {
        Icon(Icons.Default.Favorite, contentDescription = null, tint = Color.White, modifier = Modifier.fillMaxSize(0.45f))
    }
}
