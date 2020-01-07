from flask import render_template, redirect, url_for, flash, request, \
    session, jsonify, abort
from werkzeug.urls import url_parse
from flask_login import login_user, logout_user, current_user, login_required
from flask_babel import _
from app import db
from app.auth import bp
from app.auth.forms import LoginForm, RegistrationForm, \
    ResetPasswordRequestForm, ResetPasswordForm, Enable2faForm, Disable2faForm
from app.models import User
from app.auth.email import send_password_reset_email
from app.auth import authy 


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash(_('Invalid username or password'))
            return redirect(url_for('auth.login'))
        next_page = request.args.get('next')
        if not next_page or url_parse(next_page).netloc != '':
            next_page = url_for('main.index')
        if user.authy_id is not None:
            session['username'] = user.username
            return redirect(url_for(
                'auth.check_2fa', next=next_page,
                remember='1' if form.remember_me.data else '0'))
        login_user(user, remember=form.remember_me.data)
        return redirect(next_page)
    return render_template('auth/login.html', title=_('Sign In'), form=form)


@bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.index'))


@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash(_('Congratulations, you are now a registered user!'))
        return redirect(url_for('auth.login'))
    return render_template('auth/register.html', title=_('Register'),
                           form=form)


@bp.route('/reset_password_request', methods=['GET', 'POST'])
def reset_password_request():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = ResetPasswordRequestForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            send_password_reset_email(user)
        flash(
            _('Check your email for the instructions to reset your password'))
        return redirect(url_for('auth.login'))
    return render_template('auth/reset_password_request.html',
                           title=_('Reset Password'), form=form)


@bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    user = User.verify_reset_password_token(token)
    if not user:
        return redirect(url_for('main.index'))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash(_('Your password has been reset.'))
        return redirect(url_for('auth.login'))
    return render_template('auth/reset_password.html', form=form)


@bp.route('/2fa/enable', methods=['GET', 'POST'])
@login_required
def enable_2fa():
    form = Enable2faForm()
    if form.validate_on_submit():
        jwt = authy.get_registration_jwt(current_user.id)
        session['registration_jwt'] = jwt
        return render_template('auth/enable_2fa_qr.html')
    return render_template('auth/enable_2fa.html', form=form)


@bp.route('/2fa/enable/qrcode')
@login_required
def enable_2fa_qrcode():
    jwt = session.get('registration_jwt')
    if not jwt:
        abort(400)

    del session['registration_jwt']

    return authy.get_qrcode(jwt), 200, {
        'Content-Type': 'image/svg+xml',
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0'}


@bp.route('/2fa/enable/poll')
@login_required
def enable_2fa_poll():
    registration = authy.get_registration_status(current_user.id)
    if registration['status'] == 'completed':
        current_user.authy_id = registration['authy_id']
        db.session.commit()
        flash(_('You have successfully enabled two-factor authentication on '
                'your account!'))
    elif registration['status'] != 'pending':
        flash(_('An error has occurred. Please try again.'))
    return jsonify(registration['status'])


@bp.route('/2fa/disable', methods=['GET', 'POST'])
@login_required
def disable_2fa():
    form = Disable2faForm()
    if form.validate_on_submit():
        if not authy.delete_user(current_user.authy_id):
            flash(_('An error has occurred. Please try again.'))
        else:
            current_user.authy_id = None
            db.session.commit()
            flash(_('Two-factor authentication is now disabled.'))
        return redirect(url_for('main.user', username=current_user.username))
    return render_template('auth/disable_2fa.html', form=form)


@bp.route('/2fa/check')
def check_2fa():
    username = session['username']
    user = User.query.filter_by(username=username).first()
    session['authy_push_uuid'] = authy.send_push_authentication(user)
    return render_template('auth/check_2fa.html',
                           next=request.args.get('next'))


@bp.route('/2fa/check/poll')
def check_2fa_poll():
    push_status = authy.check_push_authentication_status(
        session['authy_push_uuid'])
    if push_status == 'approved':
        username = session['username']
        del session['username']
        del session['authy_push_uuid']
        user = User.query.filter_by(username=username).first()
        remember = request.args.get('remember', '0') == '1'
        login_user(user, remember=remember)
    elif push_status != 'pending':
        flash(_('An error has occurred. Please try again.'))
    return jsonify(push_status)
