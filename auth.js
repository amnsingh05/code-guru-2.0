// Firebase Authentication for CodeGuru — email/password, sign-up, Google login,
// password reset, logout, and the auth-state redirect between login.html and
// dashboard.html. Loaded as an ES module from login.html and dashboard.html.
import { firebaseConfig } from './firebase-config.js';
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.13.0/firebase-app.js";
import {
  getAuth,
  onAuthStateChanged,
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  GoogleAuthProvider,
  signInWithPopup,
  sendPasswordResetEmail,
  signOut,
  linkWithPopup,
  linkWithCredential,
  EmailAuthProvider,
} from "https://www.gstatic.com/firebasejs/10.13.0/firebase-auth.js";

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
const googleProvider = new GoogleAuthProvider();

export function signUp(email, password) {
  return createUserWithEmailAndPassword(auth, email, password);
}

export function logIn(email, password) {
  return signInWithEmailAndPassword(auth, email, password);
}

export function logInWithGoogle() {
  return signInWithPopup(auth, googleProvider);
}

export function resetPassword(email) {
  return sendPasswordResetEmail(auth, email);
}

export function logOut() {
  return signOut(auth);
}

// Connects Google to the currently signed-in email/password account. Once
// linked, either sign-in option opens the same Firebase user.
export function linkGoogleAccount() {
  if (!auth.currentUser) throw new Error('auth/no-current-user');
  return linkWithPopup(auth.currentUser, googleProvider);
}

// Adds email/password as a second sign-in method to a Google account.
export function addPasswordToAccount(password) {
  if (!auth.currentUser?.email) throw new Error('auth/no-current-user');
  return linkWithCredential(
    auth.currentUser,
    EmailAuthProvider.credential(auth.currentUser.email, password)
  );
}

// Keeps login.html and dashboard.html in sync with the user's sign-in state.
// login.html: an already-signed-in user is sent straight to the dashboard.
// dashboard.html: a signed-out user is sent back to login.
export function watchAuth({ onSignedIn, onSignedOut } = {}) {
  onAuthStateChanged(auth, (user) => {
    if (user && onSignedIn) onSignedIn(user);
    if (!user && onSignedOut) onSignedOut();
  });
}

// Turns a Firebase Auth error code into a short, student-friendly message.
export function readableAuthError(error) {
  const map = {
    'auth/email-already-in-use': 'That email already has an account. If you created it with Google, sign in with Google first and add a password from the dashboard.',
    'auth/invalid-email': 'That email address doesn\u2019t look right.',
    'auth/weak-password': 'Use at least 6 characters for your password.',
    'auth/user-not-found': 'No account found with that email.',
    'auth/wrong-password': 'That password doesn\u2019t match.',
    'auth/invalid-credential': 'Email or password is incorrect. If this account was created with Google, sign in with Google first and add a password from the dashboard.',
    'auth/too-many-requests': 'Too many attempts — wait a moment and try again.',
    'auth/popup-closed-by-user': 'Google sign-in was closed before finishing.',
    'auth/operation-not-allowed': 'Google sign-in is not enabled yet. In Firebase Console, open Authentication → Sign-in method and enable Google.',
    'auth/unauthorized-domain': 'This website domain is not authorized in Firebase. Add it under Authentication → Settings → Authorized domains.',
    'auth/popup-blocked': 'Your browser blocked the Google sign-in window. Allow pop-ups for this site, then try again.',
    'auth/network-request-failed': 'Network connection failed. Check your internet connection and try again.',
    'auth/credential-already-in-use': 'That Google account is already connected to another CodeGuru account.',
    'auth/provider-already-linked': 'Google is already connected to this account.',
    'auth/account-exists-with-different-credential': 'An email/password CodeGuru account already exists for this email. Sign in with your password first, then use “Link Google” in the dashboard.',
    'auth/requires-recent-login': 'For security, please sign in again with Google, then add your password.',
  };
  return map[error.code] || 'Something went wrong. Please try again.';
}
