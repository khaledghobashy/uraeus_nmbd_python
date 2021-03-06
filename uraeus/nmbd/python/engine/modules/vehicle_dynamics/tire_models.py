#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Jul  7 09:38:20 2019

@author: khaledghobashy
"""

import numpy as np
import scipy as sc

from ...numerics.math_funcs import A, E, G, skew

normal = np.array([[0], [0], [1]], dtype=np.float64)


def normalize(v):
    normalized = v/np.linalg.norm(v)
    return normalized


class terrain(object):

   def __init__(self):
      pass

   def get_state(self, x, y):
      return [normal, 0]


class abstract_tire(object):
    
    def __init__(self):
        self._u_history = [0]
        self._v_history = [0]
        self._s_history = [0]
        self._Fz_history = []
        self.t = 0
        self._V_low = 2.5*1e3
        
        self.driven = 1
        
    def _advance_time(self, t, dt):
        if self.t <= t:
            self.t += dt            
    
    def _process_wheel_kinematics(self, t, dt, wheel_states, drive_torque, terrain_state=None):
        
        # Extracting the wheel states
        R_hub, P_hub, Rd_hub, Pd_hub = wheel_states
        
        # 
        if terrain_state:
            terrain_normal, terrain_height = terrain_state
        else:
            terrain_normal = normal
            terrain_height = 0
        
        # Creating SAE wheel frame based on hub orientation
        self._set_SAE_Frame(P_hub, terrain_normal)
        
        # Evaluating the tire radii
        self._eval_wheel_radii(R_hub, Rd_hub, terrain_height)
        
        # Wheel Center Translational Velocity in Global Frame
        V_wc_GF  = Rd_hub
        
        # Wheel Center Translational Velocity in SAE Frame
        V_wc_SAE = self.SAE_GF.T.dot(V_wc_GF)

        AngVel_Hub_LF = 2*E(P_hub)@Pd_hub # Global
        #AngVel_Hub_LF = 2*G(P_hub)@Pd_hub # Local

        # Wheel spin velocity in SAE frame
        #Omega = AngVel_Hub_LF[1,0]
        Omega = self.SAE_GF.T.dot(AngVel_Hub_LF)[1,0]
        
        # Longitudinal Wheel Velocity in SAE frame
        #V_x  = abs(V_wc_SAE[0,0])
        V_x  = V_wc_SAE[0,0]
        
        # Circumfiranctial Velocity in SAE frame
        V_C  = Omega * self.effective_radius
        
        # Longitudinal Slip Velocity in SAE frame
        V_sx = (V_x + V_C)
        
        # Lateral Slip Velocity in SAE frame
        V_sy = V_wc_SAE[1,0]

        self.V_C = V_C
        self.V_x = V_x 
        self.V_sx = V_sx
        self.V_sy = V_sy
        self.Omega = Omega
        self.V_wc_SAE = V_wc_SAE
            
    
    def _process_wheel_kinematics_2(self, t, dt, wheel_states, drive_torque, terrain_state=None):
        
        # Extracting the wheel states
        R_hub, P_hub, Rd_hub, Pd_hub = wheel_states
        
        # 
        if terrain_state:
            terrain_normal, terrain_height = terrain_state
        else:
            terrain_normal = normal
            terrain_height = 0
        
        # Creating SAE wheel frame based on hub orientation
        self._set_SAE_Frame(P_hub, terrain_normal)
        
        # Evaluating the tire radii
        self._eval_wheel_radii(R_hub, Rd_hub, terrain_height)
        
        # Wheel Center Translational Velocity in Global Frame
        V_wc_GF  = Rd_hub
        
        # Wheel Center Translational Velocity in SAE Frame
        V_wc_SAE = self.SAE_GF.T.dot(V_wc_GF)

        # Wheel spin velocity in SAE frame
        Omega = self._solve_wheel_ODE(t, dt, drive_torque)
        
        # Circumfiranctial Velocity in SAE frame
        V_C  = Omega * self.effective_radius
        
        # Longitudinal Slip Velocity in SAE frame
        V_sx = V_wc_SAE[0,0] - V_C
        
        # Lateral Slip Velocity in SAE frame
        V_sy = V_wc_SAE[1,0]

        # Longitudinal Wheel Velocity in SAE frame
        V_x  = abs(V_wc_SAE[0,0])

        self.V_C  = V_C
        self.V_sx = V_sx
        self.V_sy = V_sy
        self.V_x  = V_x 
        self.Omega = Omega
        self.V_wc_SAE = V_wc_SAE
        

    def _set_SAE_Frame(self, P_hub, terrain_normal):
        
        frame = A(P_hub)
        
        spin_axis = frame[:,1:2]
        
        Z_SAE_GF = -terrain_normal
        X_SAE_GF = normalize(skew(spin_axis).dot(Z_SAE_GF))
        Y_SAE_GF = skew(Z_SAE_GF).dot(X_SAE_GF)
        
        self.X_SAE_GF = X_SAE_GF
        self.Y_SAE_GF = Y_SAE_GF
        self.Z_SAE_GF = Z_SAE_GF
        
        self.SAE_GF = np.concatenate([X_SAE_GF, Y_SAE_GF, Z_SAE_GF], axis=1)
        
    
    def _eval_wheel_radii(self, R_hub, Rd_hub, terrain_height = 0):
        # Loaded Radius
        self.loaded_radius = min(self.nominal_radius, R_hub[2,0] - terrain_height)
        
        # Penetration Length assuming flat horizontal ground
        self.vertical_defflection = max(self.nominal_radius - self.loaded_radius, 0)
        
        self.penetration_speed = Rd_hub[2,0] if self.vertical_defflection >0 else 0
        
        # Tire Effective Radius as a ratio of loaded radius
        self.effective_radius = self.loaded_radius + \
                                (self.vertical_defflection * (2/3))


    def _solve_wheel_ODE(self, t, dt, drive_torque):
        if self.t <= t:
            Iyy = self.Iyy
            Fx  = self.Fx
            y   = self._s_history[-1]
            Re  = self.effective_radius
            omega = self._wheel_spin_RK45(y, dt, Iyy, drive_torque, Fx, Re)
            self._s_history.append(omega)
            return omega
        else:
            return self._s_history[-1]
        
    def _wheel_spin_RK45(self, y, h, Iyy, drive_torque, Fx, Re):
        func = self._wheel_spin_ODE
        
        f1 = h*func(y, Iyy, drive_torque, Fx, Re)
        f2 = h*func(y + 0.5*f1, Iyy, drive_torque, Fx, Re)
        f3 = h*func(y + 0.5*f2, Iyy, drive_torque, Fx, Re)
        f4 = h*func(y + f3, Iyy, drive_torque, Fx, Re)
        
        dy = (1/6) * (f1 + 2*f2 + 2*f3 + f4)
        yn = y + dy  
        return yn
    
    def _wheel_spin_ODE(self, y, Iyy, drive_torque, Fx, Re):
        net_torque = abs(drive_torque) - (Fx*Re)
        dydt = (1/Iyy)*net_torque
        return dydt
            
    
    def _get_transient_slips(self, t, dt):
        
        V_sx = self.V_sx
        V_sy = self.V_sy
        V_x  = self.V_x

        self._integrate_CPM(t, dt, V_sx, V_sy, V_x)
        k =  float(self.ui/self.sigma_k)
        a =  float(self.vi/self.sigma_a)
        
        if abs(V_x) <= self._V_low:
            kv_low = 0.5*self.kv_low*(1 + np.cos(np.pi*(V_x/self._V_low)))
            damped = (kv_low/self.C_Fk)*V_sx
#            print('damped_k = %s'%damped)
            k = k - damped
            
            ka_low = 0.5*self.kv_low*(1 + np.cos(np.pi*(V_x/self._V_low)))
            damped = (ka_low/self.C_Fa)*V_sy
#            print('damped_a = %s'%damped)
            a = a - damped
        
#        print('ui = %s'%self.ui)
#        print('k = %s'%k)
#        print('vi = %s'%self.vi)
#        print('a = %s'%a)
        
        return k, a
    
    def _integrate_CPM(self, t, dt, V_sx, V_sy, Vx):
        
        if self.t <= t:
            u_old = self._u_history[-1]
            self.ui = self._integrate_CPM_RK45(dt, u_old, V_sx, self.sigma_k, Vx)
            
            v_old = self._v_history[-1]
            self.vi = self._integrate_CPM_RK45(dt, v_old, V_sy, self.sigma_a, Vx)
                        
            self._u_history.append(self.ui)
            self._v_history.append(self.vi)
            
    def _integrate_CPM_RK45(self, h, y, slip_vel, relx, Vx):
        func = self._CPM_ODE
        
        f1 = h*func(y, slip_vel, relx, Vx)
        f2 = h*func(y + 0.5*f1, slip_vel, relx, Vx)
        f3 = h*func(y + 0.5*f2, slip_vel, relx, Vx)
        f4 = h*func(y + f3, slip_vel, relx, Vx)
        
        dy = (1/6) * (f1 + 2*f2 + 2*f3 + f4)
        yn = y + dy
        
        return yn

    def _CPM_ODE(self, y, slip_vel, relx, Vx):
        
        if self.slipping:
#            print((slip_vel + (Vx*y)/relx) * y)
            dydt = 0
        else:
            dydt = -(1/relx)*Vx*y - slip_vel
        return dydt

    def _log_Fz(self, t):
        if self.t <= t:
            self._Fz_history.append(self.Fz)
            

###############################################################################
###############################################################################

class brush_model(abstract_tire):
    
    def __init__(self):
        
        self.nominal_radius = 546
        self.mu = 0.85
        self.cp = 1500*1e3
        self.a  = 210
        
        self.kz = 650*1e6
        self.cz = 10*1e6
        
        C_fk = (2375*9.81*1e6*0.2)/(3*1e-2)
        C_fa = (150*1e6*1e2)/(np.deg2rad(2))
        C_fx = C_fy = self.cp
        
        self.sigma_k = (C_fk/C_fx)*1e-3
        self.sigma_a = (C_fa/C_fy)*1e-3
        
        self.C_Fk = C_fk
        self.C_Fa = C_fa
        
        self.kv_low = 770*1e3 # 770 Ns/m Damping coefficient at low speeds
        
        self.Iyy = 50*1e9
        self.Fx  = 0
        self.slipping = False
        
        self.F = np.zeros((3,1))
        self.M = np.zeros((3,1))
        
        super().__init__()
    
    
    
    def Eval_Forces(self, t, dt, wheel_states, drive_torque, terrain_state=None):
        
        self._process_wheel_kinematics(t, dt, wheel_states, drive_torque, terrain_state)
        
        self.Fz =  (self.kz * self.vertical_defflection) \
                 - (self.cz * self.penetration_speed)
        

        k, alpha = self._get_transient_slips(t, dt)
        
        sigma_x = k/(1+k)
        sigma_y = np.tan(alpha)/(1+k)
        sigma   = np.sqrt(sigma_x**2 + sigma_y**2)
        sigma_vec = np.array([[sigma_x], [sigma_y]])

        
        if sigma <= 1e-5 or self.Fz <= 0:
            F  = np.array([[0], [0]])
            xt = 0

        else:
            Theta = (2/3)*((self.cp * self.a**2)/(self.mu*self.Fz))
            TG = Theta*sigma

            if sigma <= 1/Theta:
                self.slipping = False
                factor = (3*(TG) - 3*(TG)**2 + (TG)**3)
                force  = self.mu * self.Fz * factor
            else:
                print('SLIDING !!')
                factor = 0.65
                force = self.mu * self.Fz * factor
                self.slipping = True
            
            F  = force * normalize(sigma_vec)
            # Pneumatic Trail
            xt = (1/3)*self.a * ((1 - 3*abs(TG) + 3*TG**2 - abs(TG)**3) /
                                 (1 - abs(TG) + (1/3)*TG**2 ))
        
        self.Fx = F[0,0]
        self.Fy = F[1,0]
        
        # Self Aligning Moment in SAE Frame
        self.Mz = (- xt * self.Fy)

        self._eval_GF_forces()
        
        self._log_Fz(t)
        
        # Advancing the time stamp in the tire model
        self._advance_time(t, dt)


    def _eval_GF_forces(self):
        
        F = np.array([[self.Fx], [self.Fy], [-self.Fz]])
        
        self.F = self.SAE_GF.dot(F)
        self.My = self.Fx * self.effective_radius

#        X_SAE_GF = self.X_SAE_GF
        Y_SAE_GF = self.Y_SAE_GF
        Z_SAE_GF = self.Z_SAE_GF

        M_SAE = np.array([[0], [self.My], [self.Mz]])
        M_GF = self.SAE_GF @ M_SAE

        self.M  = M_GF 
        #self.M = (self.My * Y_SAE_GF) + (self.Mz * Z_SAE_GF)
#        print('My_SAE = %s'%self.My)
#        print('M = %s'%(self.M.T))
        
    
###############################################################################
###############################################################################

