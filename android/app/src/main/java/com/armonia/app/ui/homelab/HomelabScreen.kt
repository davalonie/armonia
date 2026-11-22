package com.armonia.app.ui.homelab

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import com.armonia.app.homelab.Recording

@Composable
fun HomelabScreen(section:Int=0, onSearch:(String)->Unit={}, vm:HomelabViewModel=hiltViewModel()) {
    val offlineProblem by vm.offlineProblem.collectAsState()
    val listeningProblem by vm.listenOutbox.persistenceProblem.collectAsState()
    val tab = section
    DisposableEffect(Unit){onDispose{vm.player.stopAudition()}}
    LaunchedEffect(section){if(section==2)vm.top()}
    var username by remember{mutableStateOf("")}
    var password by remember{mutableStateOf("")}
    var artist by remember{mutableStateOf("")}
    var title by remember{mutableStateOf("")}
    var delete by remember{mutableStateOf(false)}
    if(delete) AlertDialog(onDismissRequest={delete=false},title={Text("Eliminar playlist")},
        text={Text("Solo se elimina la lista. Los archivos musicales se conservan.")},
        confirmButton={TextButton(onClick={delete=false;vm.delete()}){Text("Eliminar")}},
        dismissButton={TextButton(onClick={delete=false}){Text("Cancelar")}})
    Column(Modifier.fillMaxSize().statusBarsPadding()) {
        Text(listOf("Inicio","Playlists con canciones externas","Tus escuchas","Fuentes y recomendaciones")[tab],style=MaterialTheme.typography.headlineMedium,modifier=Modifier.padding(16.dp))
        if(vm.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
        offlineProblem?.let{Text(it,Modifier.padding(12.dp),color=MaterialTheme.colorScheme.error)}
        listeningProblem?.let{Text(it,Modifier.padding(12.dp),color=MaterialTheme.colorScheme.error)}
        vm.error?.let{Text(it,Modifier.padding(12.dp),color=MaterialTheme.colorScheme.error)}
        LazyColumn(contentPadding=PaddingValues(16.dp),verticalArrangement=Arrangement.spacedBy(12.dp)) {
            item {OutlinedButton(onClick={vm.load()},enabled=!vm.busy){Text("Actualizar")}}
            if(tab==3){
                item{Text("Armonía semanal",style=MaterialTheme.typography.headlineSmall);Text("Escuchar no añade canciones a la biblioteca.");Button(onClick={vm.weekly()},enabled=!vm.busy){Text("Activar lista semanal")}}
                items(vm.flows){f->Row{OutlinedButton(onClick={vm.flow(f.id)},enabled=!vm.busy){Text(if(f.name.startsWith("Armonía Weekly"))"Mi Armonía semanal" else f.name)};TextButton(onClick={vm.refreshFlow(f.id)},enabled=!vm.busy){Text("Regenerar")}}}
                items(vm.recommendations){t->ListItem(headlineContent={Text(t.title)},supportingContent={Text(t.artist)},trailingContent={TextButton(onClick={vm.match(t)}){Text("Escuchar")}})}
                item{Text("Similares a tus artistas identificados",style=MaterialTheme.typography.titleLarge);if(vm.artists.isEmpty()) Text(if(vm.discoveryState=="unavailable") "Metadatos no disponibles; vuelve a actualizar." else if(vm.discoveryState=="no_similar_results") "Artistas identificados; el proveedor no ha devuelto similitudes. Vuelve a actualizar." else "Perfil insuficiente o artistas pendientes de identificar.")}
                items(vm.discoverySeeds){s->ListItem(headlineContent={Text(s.name)},supportingContent={Text(s.explanation())})}
                items(vm.artists){a->TextButton(onClick={onSearch(a.name)}){Text("${a.name} · Similar a ${a.sourceArtist.orEmpty()}")}}
                item{Text("Recomendaciones recientes",style=MaterialTheme.typography.titleLarge)}
                items(vm.recent){t->TextButton(onClick={vm.match(t)}){Text("${t.artist} — ${t.title}")}}
            }
            if(tab==1){
                mixedPlaylists(vm, onDelete={delete=true})
            }else if(tab==3){
                item{Text("Buscar grabación",style=MaterialTheme.typography.titleLarge)
                    OutlinedTextField(value=artist,onValueChange={artist=it},label={Text("Artista")},modifier=Modifier.fillMaxWidth())
                    OutlinedTextField(value=title,onValueChange={title=it},label={Text("Canción")},modifier=Modifier.fillMaxWidth())
                    Button(onClick={vm.match(Recording(title,artist))},enabled=title.isNotBlank()&&artist.isNotBlank()&&!vm.busy){Text("Buscar coincidencias")}}
                item{Text("Fuentes disponibles",style=MaterialTheme.typography.titleLarge)}
                items(vm.sources){t->ListItem(headlineContent={Text(t.title)},supportingContent={Text(t.artist)},trailingContent={Column{TextButton(onClick={vm.play(t)}){Text("Escuchar")};if(t.source=="authorized_http")TextButton(onClick={vm.saveSource(t)},enabled=!vm.busy){Text("Guardar")}}})}
                item{Text("Cuenta de recomendaciones",style=MaterialTheme.typography.titleLarge)
                    OutlinedTextField(value=username,onValueChange={username=it},label={Text("Usuario Aurral")},modifier=Modifier.fillMaxWidth())
                    OutlinedTextField(value=password,onValueChange={password=it},label={Text("Contraseña Aurral")},visualTransformation=PasswordVisualTransformation(),modifier=Modifier.fillMaxWidth())
                    Button(onClick={vm.link(username,password);password=""},enabled=!vm.busy&&username.isNotBlank()&&password.isNotBlank()){Text("Vincular")}}
            }else if(tab==2){
                item{Text("Estadísticas privadas",style=MaterialTheme.typography.headlineSmall);Row{TextButton(onClick={vm.top("artists")}){Text("Artistas")};TextButton(onClick={vm.top("tracks")}){Text("Canciones")};TextButton(onClick={vm.top("albums")}){Text("Álbumes")}}}
                items(vm.stats){row->ListItem(headlineContent={Text(row.first)},trailingContent={Text("${row.second} escuchas")})}
            }
            if (tab == 3) {
                vm.reviewOriginal?.let { original -> item { Text("Opciones para ${original.artist} — ${original.title}",style=MaterialTheme.typography.titleMedium) } }
                items(vm.candidates){c->ListItem(headlineContent={Text(c.track.title)},supportingContent={Text("${c.track.artist} · ${c.track.duration?:"?"} s")},leadingContent={TextButton(onClick={vm.player.audition(c.track.toSong())}){Text("▶ 10 s")}},trailingContent={TextButton(onClick={vm.play(c.track)}){Text("Reproducir")}})}
                if(vm.candidates.isNotEmpty())item{TextButton(onClick={vm.player.stopAudition()}){Text("Volver a mi reproducción en pausa")}}
            }
            item{Spacer(Modifier.height(30.dp))}
        }
    }
}
