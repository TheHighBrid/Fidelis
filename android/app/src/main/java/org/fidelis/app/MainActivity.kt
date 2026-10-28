package org.fidelis.app

import android.annotation.SuppressLint
import android.app.AlertDialog
import android.app.DownloadManager
import android.content.ContentValues
import android.content.Intent
import android.graphics.Bitmap
import android.media.MediaScannerConnection
import android.net.Uri
import android.net.http.SslError
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.util.Base64
import android.view.View
import android.webkit.*
import android.widget.EditText
import android.widget.ImageButton
import android.widget.ProgressBar
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import java.io.File
import java.io.FileOutputStream

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var progressBar: ProgressBar
    private lateinit var btnSettings: ImageButton
    private var fileUploadCallback: ValueCallback<Array<Uri>>? = null

    private val filePickerLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK) {
            val data: Intent? = result.data
            val results: Array<Uri>? = when {
                data?.data != null -> arrayOf(data.data!!)
                data?.clipData != null -> {
                    val count = data.clipData!!.itemCount
                    Array(count) { i -> data.clipData!!.getItemAt(i).uri }
                }
                else -> null
            }
            fileUploadCallback?.onReceiveValue(results)
        } else {
            fileUploadCallback?.onReceiveValue(null)
        }
        fileUploadCallback = null
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        webView = findViewById(R.id.webView)
        progressBar = findViewById(R.id.progressBar)
        btnSettings = findViewById(R.id.btnSettings)

        btnSettings.setOnClickListener {
            promptServerUrl("Configure Fidelis Studio URL:")
        }

        setupWebView()

        val prefs = getSharedPreferences("fidelis_prefs", MODE_PRIVATE)
        val defaultUrl = prefs.getString("server_url", "http://51.79.71.248:8080") ?: "http://51.79.71.248:8080"
        loadUrlWithFallback(defaultUrl)
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        val settings = webView.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.databaseEnabled = true
        settings.allowFileAccess = true
        settings.allowContentAccess = true
        settings.useWideViewPort = true
        settings.loadWithOverviewMode = true
        settings.setSupportZoom(true)
        settings.builtInZoomControls = true
        settings.displayZoomControls = false
        settings.mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW

        webView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                progressBar.visibility = View.VISIBLE
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                progressBar.visibility = View.GONE
            }

            @SuppressLint("WebViewClientOnReceivedSslError")
            override fun onReceivedSslError(
                view: WebView?,
                handler: SslErrorHandler?,
                error: SslError?
            ) {
                // Allow self-signed or raw-IP SSL certs so webview doesn't freeze white
                handler?.proceed()
            }

            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?
            ) {
                if (request?.isForMainFrame == true) {
                    progressBar.visibility = View.GONE
                    val desc = error?.description ?: "Connection failed"
                    Toast.makeText(this@MainActivity, "Connection failed: $desc", Toast.LENGTH_SHORT).show()
                    promptServerUrl("Connection error: $desc\nFailed URL: ${request.url}\n\nPlease check your Fidelis Studio URL:")
                }
            }

            @Suppress("DEPRECATION")
            override fun onReceivedError(
                view: WebView?,
                errorCode: Int,
                description: String?,
                failingUrl: String?
            ) {
                progressBar.visibility = View.GONE
                promptServerUrl("Connection error: $description\n\nPlease check your Fidelis Studio URL:")
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                mWebView: WebView?,
                filePathCallback: ValueCallback<Array<Uri>>?,
                fileChooserParams: FileChooserParams?
            ): Boolean {
                fileUploadCallback?.onReceiveValue(null)
                fileUploadCallback = filePathCallback

                val intent = fileChooserParams?.createIntent() ?: Intent(Intent.ACTION_GET_CONTENT).apply {
                    type = "image/*"
                    addCategory(Intent.CATEGORY_OPENABLE)
                }

                try {
                    filePickerLauncher.launch(intent)
                } catch (e: Exception) {
                    fileUploadCallback = null
                    return false
                }
                return true
            }
        }

        webView.addJavascriptInterface(WebAppInterface(this), "AndroidApp")

        webView.setDownloadListener { url, _, contentDisposition, mimetype, _ ->
            val filename = URLUtil.guessFileName(url, contentDisposition, mimetype) ?: "fidelis_upscaled.png"
            if (url.startsWith("data:")) {
                saveBase64ToGallery(url, filename)
            } else {
                downloadHttpFile(url, filename)
            }
        }
    }

    inner class WebAppInterface(private val activity: MainActivity) {
        @JavascriptInterface
        fun saveImage(base64Data: String, filename: String?) {
            activity.runOnUiThread {
                activity.saveBase64ToGallery(base64Data, filename ?: "fidelis_upscaled.png")
            }
        }

        @JavascriptInterface
        fun downloadFromUrl(fileUrl: String, filename: String?) {
            activity.runOnUiThread {
                activity.downloadHttpFile(fileUrl, filename ?: "fidelis_upscaled.png")
            }
        }
    }

    fun saveBase64ToGallery(base64Data: String, filename: String) {
        try {
            val cleanBase64 = if (base64Data.contains(",")) {
                base64Data.substringAfter(",")
            } else {
                base64Data
            }
            val bytes = Base64.decode(cleanBase64, Base64.DEFAULT)
            saveBytesToGallery(bytes, filename)
        } catch (e: Exception) {
            Toast.makeText(this, "Failed to decode image: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }

    fun saveBytesToGallery(bytes: ByteArray, filename: String) {
        val name = if (filename.endsWith(".png", ignoreCase = true) || filename.endsWith(".jpg", ignoreCase = true)) {
            filename
        } else {
            "fidelis_${System.currentTimeMillis()}.png"
        }

        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val contentValues = ContentValues().apply {
                    put(MediaStore.MediaColumns.DISPLAY_NAME, name)
                    put(MediaStore.MediaColumns.MIME_TYPE, "image/png")
                    put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/Fidelis")
                    put(MediaStore.Images.Media.IS_PENDING, 1)
                }
                val uri = contentResolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, contentValues)
                if (uri != null) {
                    contentResolver.openOutputStream(uri)?.use { out ->
                        out.write(bytes)
                        out.flush()
                    }
                    contentValues.clear()
                    contentValues.put(MediaStore.Images.Media.IS_PENDING, 0)
                    contentResolver.update(uri, contentValues, null, null)
                    Toast.makeText(this, "Saved to Pictures/Fidelis: $name", Toast.LENGTH_LONG).show()
                    return
                }
            }

            // Fallback for API < 29
            val picturesDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES)
            val fidelisDir = File(picturesDir, "Fidelis")
            if (!fidelisDir.exists()) fidelisDir.mkdirs()
            val file = File(fidelisDir, name)
            FileOutputStream(file).use { out ->
                out.write(bytes)
                out.flush()
            }
            MediaScannerConnection.scanFile(this, arrayOf(file.absolutePath), arrayOf("image/png"), null)
            Toast.makeText(this, "Saved to Pictures/Fidelis: $name", Toast.LENGTH_LONG).show()
        } catch (e: Exception) {
            Toast.makeText(this, "Failed to save picture: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }

    fun downloadHttpFile(fileUrl: String, filename: String) {
        try {
            val uri = Uri.parse(fileUrl)
            val request = DownloadManager.Request(uri).apply {
                setTitle(filename)
                setDescription("Downloading upscaled image from Fidelis Studio...")
                setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                setDestinationInExternalPublicDir(Environment.DIRECTORY_PICTURES, "Fidelis/$filename")
                setMimeType("image/png")
            }
            val dm = getSystemService(DOWNLOAD_SERVICE) as DownloadManager
            dm.enqueue(request)
            Toast.makeText(this, "Downloading $filename to Pictures/Fidelis...", Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            Thread {
                try {
                    val conn = java.net.URL(fileUrl).openConnection()
                    val bytes = conn.getInputStream().use { it.readBytes() }
                    runOnUiThread {
                        saveBytesToGallery(bytes, filename)
                    }
                } catch (err: Exception) {
                    runOnUiThread {
                        Toast.makeText(this, "Download failed: ${err.message}", Toast.LENGTH_LONG).show()
                    }
                }
            }.start()
        }
    }

    private fun loadUrlWithFallback(url: String) {
        webView.loadUrl(url)
    }

    private fun promptServerUrl(message: String) {
        val input = EditText(this)
        val prefs = getSharedPreferences("fidelis_prefs", MODE_PRIVATE)
        val current = prefs.getString("server_url", "http://51.79.71.248:8080")
        input.setText(current)
        input.hint = "http://51.79.71.248:8080"

        AlertDialog.Builder(this)
            .setTitle("Fidelis Studio Connection")
            .setMessage(message)
            .setView(input)
            .setPositiveButton("Connect") { _, _ ->
                var newUrl = input.text.toString().trim()
                if (newUrl.isNotEmpty() && !newUrl.startsWith("http://") && !newUrl.startsWith("https://")) {
                    newUrl = "http://$newUrl"
                }
                prefs.edit().putString("server_url", newUrl).apply()
                webView.loadUrl(newUrl)
            }
            .setNegativeButton("Retry") { _, _ ->
                webView.reload()
            }
            .setCancelable(false)
            .show()
    }

    override fun onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack()
        } else {
            super.onBackPressed()
        }
    }
}
