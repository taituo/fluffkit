import org.jetbrains.kotlin.gradle.dsl.JvmTarget
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// The persona, config and pack map are the same files the Chrome page uses (../phone); they are copied
// into the APK at build time so the app and the page never drift apart.
abstract class CopyPhoneAssets : DefaultTask() {
    @get:InputFiles abstract val sources: ConfigurableFileCollection
    @get:InputFiles abstract val personas: ConfigurableFileCollection
    @get:OutputDirectory abstract val outputDir: DirectoryProperty

    @TaskAction fun run() {
        val out = outputDir.get().asFile
        out.deleteRecursively(); out.mkdirs()
        sources.files.filter { it.exists() }.forEach { it.copyTo(File(out, it.name), overwrite = true) }
        personas.files.forEach { it.copyTo(File(out, "personas/${it.name}"), overwrite = true) }
    }
}

// -PphoneDir=/path/to/phone builds with another checkout's (e.g. uncommitted) persona and config
val phone = (findProperty("phoneDir") as String?)?.let { file(it) } ?: rootProject.file("../phone")
val copyPhoneAssets = tasks.register<CopyPhoneAssets>("copyPhoneAssets") {
    sources.from(File(phone, "furby-config.json"), File(phone, "packs.json"), File(phone, "furby-agent/AGENTS.md"),
        File(phone, "furby-agent/common.md"))
    personas.from(fileTree(File(phone, "furby-agent/personas")) { include("*.md") })
}

// bumped by release.sh for every APK that goes to the phone, so versions can be told apart
val version = Properties().apply { rootProject.file("version.properties").inputStream().use { load(it) } }

android {
    namespace = "fluffkit.companion"
    compileSdk = 36

    defaultConfig {
        applicationId = "fluffkit.companion"
        minSdk = 29
        targetSdk = 36
        versionCode = version.getProperty("code").toInt()
        versionName = version.getProperty("name")
    }
    buildTypes {
        release { isMinifyEnabled = false; signingConfig = signingConfigs.getByName("debug") }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin { compilerOptions { jvmTarget.set(JvmTarget.JVM_17) } }

androidComponents {
    onVariants { variant ->
        variant.sources.assets?.addGeneratedSourceDirectory(copyPhoneAssets, CopyPhoneAssets::outputDir)
    }
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("androidx.security:security-crypto:1.1.0")
    implementation("androidx.core:core-ktx:1.16.0")
}
