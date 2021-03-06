package labs.pooh.eaterslab.util

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.pm.PackageManager
import android.widget.Toast
import android.widget.Toast.LENGTH_LONG
import android.widget.Toast.LENGTH_SHORT
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

internal const val LOCATION_PERMISSION = Manifest.permission.ACCESS_FINE_LOCATION

fun hasPermission(context: Context, permission: String): Boolean
        = ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED

fun Activity.requestListedPermission(requestCode: Int, vararg permissions: String)
        = ActivityCompat.requestPermissions(this, arrayOf(*permissions), requestCode)

fun allRequestedPermissionsGranted(grantResults: IntArray)
        = grantResults.none { it == PackageManager.PERMISSION_DENIED }

fun Context.sendNotification(text: String, shortDuration: Boolean = true)
        = Toast.makeText(this, text, if (shortDuration) LENGTH_SHORT else LENGTH_LONG).show()
