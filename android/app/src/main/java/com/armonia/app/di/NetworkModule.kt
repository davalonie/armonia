package com.armonia.app.di

import com.google.gson.Gson
import com.google.gson.GsonBuilder
import com.armonia.app.BuildConfig
import com.armonia.app.data.api.ArmoniaApi
import com.armonia.app.data.api.isSessionInvalidResponse
import com.armonia.app.data.api.SearchResponse
import com.armonia.app.data.api.SearchResponseDeserializer
import com.armonia.app.data.repository.PreferencesRepository
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit
import javax.inject.Named
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    @Provides
    @Singleton
    fun provideGson(): Gson = GsonBuilder()
        .registerTypeAdapter(SearchResponse::class.java, SearchResponseDeserializer())
        .create()

    @Provides
    @Singleton
    fun provideLoggingInterceptor(): HttpLoggingInterceptor {
        return HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.NONE
        }
    }

    @Provides
    @Singleton
    @Named("auth")
    fun provideAuthInterceptor(prefs: PreferencesRepository): Interceptor {
        return Interceptor { chain ->
            val auth = chain.request().tag(com.armonia.app.data.repository.AuthSnapshot::class.java) ?: prefs.cachedAuth
            val sessionId = auth.sessionId
            val request = chain.request().newBuilder()
            if (sessionId.isNotEmpty() && com.armonia.app.security.AccountScope.sameOrigin(chain.request().url.toString(), auth.serverUrl) && chain.request().url.encodedPath != "/api/login") {
                request.header("X-Session-Id", sessionId)
                if (chain.request().header("X-Music-Owner") == null && auth.userId.isNotBlank()) request.header("X-Music-Owner",auth.userId)
            }
            val response = chain.proceed(request.build())
            // The server no longer knows our session (expired, or dropped by a backend
            // upgrade/restart). Forget it so MainActivity falls back to the login
            // screen instead of every screen — and Android Auto — silently showing
            // nothing.
            if (sessionId.isNotEmpty() && sessionId == prefs.cachedSessionId &&
                isSessionInvalidResponse(response.request.url.encodedPath, response.code)
            ) {
                runBlocking { prefs.clearSessionIfCurrent(sessionId) }
            }
            response
        }
    }

    @Provides
    @Singleton
    @Named("dynamicBaseUrl")
    fun provideDynamicBaseUrlInterceptor(prefs: PreferencesRepository): Interceptor {
        return Interceptor { chain ->
            var request = chain.request()
            val auth = request.tag(com.armonia.app.data.repository.AuthSnapshot::class.java) ?: prefs.cachedAuth
            val serverUrl = auth.serverUrl
            if (serverUrl.isNotBlank()) {
                try {
                    val normalized = if (serverUrl.contains("://")) serverUrl else "http://$serverUrl"
                    val base = normalized.toHttpUrl()
                    val newUrl = request.url.newBuilder()
                        .scheme(base.scheme)
                        .host(base.host)
                        .port(base.port)
                        .build()
                    request = request.newBuilder().url(newUrl).tag(com.armonia.app.data.repository.AuthSnapshot::class.java,auth).build()
                } catch (e: Exception) {
                    // Fallback if parsing fails
                }
            }
            chain.proceed(request)
        }
    }

    @Provides
    @Singleton
    fun provideOkHttpClient(
        loggingInterceptor: HttpLoggingInterceptor,
        @Named("auth") authInterceptor: Interceptor,
        @Named("dynamicBaseUrl") dynamicBaseUrlInterceptor: Interceptor
    ): OkHttpClient {
        return OkHttpClient.Builder()
            .addInterceptor(com.armonia.app.homelab.ManualInboxUploadTimeout())
            .followRedirects(false).followSslRedirects(false)
            .addInterceptor(dynamicBaseUrlInterceptor)
            .addInterceptor(loggingInterceptor)
            .addInterceptor(authInterceptor)
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .build()
    }

    @Provides
    @Singleton
    fun provideArmoniaApi(okHttpClient: OkHttpClient, gson: Gson, prefs: PreferencesRepository): ArmoniaApi {
        // Use a stable base URL or a placeholder since the interceptor handles the actual routing
        val initialUrl = "http://placeholder/"

        return Retrofit.Builder()
            .baseUrl(initialUrl)
            .callFactory(com.armonia.app.security.SessionCallFactory(okHttpClient) { prefs.cachedAuth })
            .addConverterFactory(GsonConverterFactory.create(gson))
            .build()
            .create(ArmoniaApi::class.java)
    }
    @Provides @Singleton
    fun provideMusicApi(client: OkHttpClient, gson: Gson, prefs: PreferencesRepository): com.armonia.app.homelab.MusicApi = Retrofit.Builder()
        .baseUrl("http://placeholder/").callFactory(com.armonia.app.security.SessionCallFactory(client) { prefs.cachedAuth })
        .addConverterFactory(GsonConverterFactory.create(gson))
        .build().create(com.armonia.app.homelab.MusicApi::class.java)

}
